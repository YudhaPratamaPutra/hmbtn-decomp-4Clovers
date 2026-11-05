"""JAL callsite scanning and guarded patch planning for PS1 MIPS binaries.

The caller must provide the runtime virtual address corresponding to byte zero
of the supplied image. No load address or file mapping is inferred.
"""
from __future__ import annotations

import json
import struct
from dataclasses import dataclass

MASK32 = 0xFFFFFFFF
JAL_OPCODE = 3


class JalEngineError(ValueError):
    pass


@dataclass(frozen=True)
class JalCallsite:
    file_offset: int
    pc: int
    target: int
    instruction: int

    def to_dict(self) -> dict:
        return {
            "file_offset": f"0x{self.file_offset:X}",
            "pc": f"0x{self.pc:08X}",
            "target": f"0x{self.target:08X}",
            "instruction": f"0x{self.instruction:08X}",
        }


@dataclass(frozen=True)
class JalPatch:
    file_offset: int
    base_address: int
    pc: int
    old_target: int
    new_target: int
    expected_word: int
    replacement_word: int

    def to_dict(self) -> dict:
        return {
            "file_offset": f"0x{self.file_offset:X}",
            "base_address": f"0x{self.base_address:08X}",
            "pc": f"0x{self.pc:08X}",
            "old_target": f"0x{self.old_target:08X}",
            "new_target": f"0x{self.new_target:08X}",
            "expected_word": f"0x{self.expected_word:08X}",
            "replacement_word": f"0x{self.replacement_word:08X}",
        }


def _decode_jal(pc: int, word: int) -> int:
    if (word >> 26) != JAL_OPCODE:
        raise JalEngineError(f"word 0x{word:08X} is not JAL")
    return (((pc + 4) & 0xF0000000) | ((word & 0x03FFFFFF) << 2)) & MASK32


def _encode_jal(pc: int, target: int) -> int:
    if pc < 0 or pc > MASK32 or target < 0 or target > MASK32:
        raise JalEngineError("PC and target must be unsigned 32-bit addresses")
    if pc & 3 or target & 3:
        raise JalEngineError("PC and target must be 4-byte aligned")
    if ((pc + 4) & 0xF0000000) != (target & 0xF0000000):
        raise JalEngineError("target is outside the PC+4 pseudo-direct region")
    return 0x0C000000 | ((target >> 2) & 0x03FFFFFF)


def scan_jal(data: bytes, base_address: int, *, start_offset: int = 0,
             end_offset: int | None = None, target: int | None = None) -> list[JalCallsite]:
    """Scan aligned words for JAL. base_address maps data[0] to runtime memory."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise JalEngineError("data must be bytes-like")
    if base_address < 0 or base_address > MASK32 or base_address & 3:
        raise JalEngineError("base_address must be an aligned unsigned 32-bit address")
    end = (len(data) & ~3) if end_offset is None else end_offset
    if start_offset < 0 or end < start_offset or end > len(data):
        raise JalEngineError("scan range is outside the supplied image")
    if start_offset & 3 or end & 3:
        raise JalEngineError("scan range offsets must be 4-byte aligned")
    if end and base_address + end - 4 > MASK32:
        raise JalEngineError("scan mapping exceeds the 32-bit address space")
    if target is not None and (target < 0 or target > MASK32 or target & 3):
        raise JalEngineError("target filter must be an aligned unsigned 32-bit address")

    found = []
    for offset in range(start_offset, end, 4):
        word = struct.unpack_from("<I", data, offset)[0]
        if (word >> 26) != JAL_OPCODE:
            continue
        pc = base_address + offset
        destination = _decode_jal(pc, word)
        if target is None or destination == target:
            found.append(JalCallsite(offset, pc, destination, word))
    return found


def plan_jal_patch(data: bytes, file_offset: int, base_address: int,
                   new_target: int, *, expected_word: int,
                   expected_target: int | None = None) -> JalPatch:
    """Create a patch record only when the existing word is the expected JAL."""
    if file_offset < 0 or file_offset & 3 or file_offset + 4 > len(data):
        raise JalEngineError("callsite offset is unaligned or outside the image")
    if base_address < 0 or base_address > MASK32 or base_address & 3:
        raise JalEngineError("base_address must be an aligned unsigned 32-bit address")
    if expected_word < 0 or expected_word > MASK32:
        raise JalEngineError("expected_word must be an unsigned 32-bit instruction")
    actual = struct.unpack_from("<I", data, file_offset)[0]
    if actual != expected_word:
        raise JalEngineError(
            f"original-word mismatch: found 0x{actual:08X}, expected 0x{expected_word:08X}"
        )
    if base_address + file_offset > MASK32:
        raise JalEngineError("callsite mapping exceeds the 32-bit address space")
    pc = base_address + file_offset
    old_target = _decode_jal(pc, actual)
    if expected_target is not None and old_target != expected_target:
        raise JalEngineError(
            f"original-target mismatch: found 0x{old_target:08X}, "
            f"expected 0x{expected_target:08X}"
        )
    replacement = _encode_jal(pc, new_target)
    return JalPatch(file_offset, base_address, pc, old_target, new_target, actual, replacement)


def apply_jal_patches(data: bytes, patches: list[JalPatch]) -> bytes:
    """Apply a batch atomically after validating every original word and overlap."""
    seen = set()
    for patch in patches:
        if patch.file_offset in seen:
            raise JalEngineError(f"duplicate patch offset 0x{patch.file_offset:X}")
        seen.add(patch.file_offset)
        if patch.file_offset < 0 or patch.file_offset & 3 or patch.file_offset + 4 > len(data):
            raise JalEngineError("patch offset is unaligned or outside the image")
        if patch.base_address < 0 or patch.base_address > MASK32 or patch.base_address & 3:
            raise JalEngineError("patch record has invalid base address")
        if patch.base_address + patch.file_offset > MASK32 or patch.pc != patch.base_address + patch.file_offset:
            raise JalEngineError("patch record PC does not match its file mapping")
        actual = struct.unpack_from("<I", data, patch.file_offset)[0]
        if actual != patch.expected_word:
            raise JalEngineError(
                f"original-word mismatch at 0x{patch.file_offset:X}: "
                f"found 0x{actual:08X}, expected 0x{patch.expected_word:08X}"
            )
        if _decode_jal(patch.pc, actual) != patch.old_target:
            raise JalEngineError("patch record old target does not match original instruction")
        if _encode_jal(patch.pc, patch.new_target) != patch.replacement_word:
            raise JalEngineError("patch record replacement word is inconsistent")

    output = bytearray(data)
    for patch in patches:
        struct.pack_into("<I", output, patch.file_offset, patch.replacement_word)
    return bytes(output)


def patches_to_json(patches: list[JalPatch]) -> str:
    return json.dumps([patch.to_dict() for patch in patches], indent=2)

"""Fail-closed function-entry hook planning and binary application.

The caller supplies both file offsets and runtime addresses. This module never
infers overlay placement or trampoline storage.
"""
from __future__ import annotations

import json
import struct
from dataclasses import dataclass

from .core import MipsDecodeError, decode

MASK32 = 0xFFFFFFFF
HOOK_SIZE = 8
TRAMPOLINE_SIZE = 16


class HookEngineError(ValueError):
    pass


def _check_address(value: int, name: str) -> None:
    if (isinstance(value, bool) or not isinstance(value, int)
            or value < 0 or value > MASK32 or value & 3):
        raise HookEngineError(f"{name} must be an aligned unsigned 32-bit address")


def _encode_j(pc: int, target: int) -> int:
    _check_address(pc, "jump PC")
    _check_address(target, "jump target")
    if ((pc + 4) & 0xF0000000) != (target & 0xF0000000):
        raise HookEngineError("jump target is outside the PC+4 pseudo-direct region")
    return 0x08000000 | ((target >> 2) & 0x03FFFFFF)


@dataclass(frozen=True)
class HookPatchPlan:
    site_offset: int
    site_pc: int
    hook_pc: int
    trampoline_offset: int
    trampoline_pc: int
    original_words: tuple[int, int]
    expected_trampoline: bytes
    hook_words: tuple[int, int]
    trampoline_words: tuple[int, int, int, int]

    def to_dict(self) -> dict:
        return {
            "site_offset": f"0x{self.site_offset:X}",
            "site_pc": f"0x{self.site_pc:08X}",
            "hook_pc": f"0x{self.hook_pc:08X}",
            "trampoline_offset": f"0x{self.trampoline_offset:X}",
            "trampoline_pc": f"0x{self.trampoline_pc:08X}",
            "original_words": [f"0x{x:08X}" for x in self.original_words],
            "expected_trampoline": self.expected_trampoline.hex(),
            "hook_words": [f"0x{x:08X}" for x in self.hook_words],
            "trampoline_words": [f"0x{x:08X}" for x in self.trampoline_words],
        }


def plan_hook_patch(data: bytes, *, site_offset: int, site_pc: int,
                    hook_pc: int, trampoline_offset: int, trampoline_pc: int,
                    expected_original_words: tuple[int, int],
                    expected_trampoline: bytes) -> HookPatchPlan:
    """Plan an 8-byte entry hook and 16-byte trampoline with exact byte guards."""
    for value, name in ((site_pc, "site_pc"), (hook_pc, "hook_pc"),
                        (trampoline_pc, "trampoline_pc")):
        _check_address(value, name)
    if (isinstance(site_offset, bool) or not isinstance(site_offset, int)
            or site_offset < 0 or site_offset & 3):
        raise HookEngineError("site_offset must be a non-negative aligned file offset")
    if (isinstance(trampoline_offset, bool) or not isinstance(trampoline_offset, int)
            or trampoline_offset < 0 or trampoline_offset & 3):
        raise HookEngineError("trampoline_offset must be a non-negative aligned file offset")
    if site_offset + HOOK_SIZE > len(data):
        raise HookEngineError("hook site is outside the supplied image")
    if trampoline_offset + TRAMPOLINE_SIZE > len(data):
        raise HookEngineError("trampoline storage is outside the supplied image")
    if not (site_offset + HOOK_SIZE <= trampoline_offset
            or trampoline_offset + TRAMPOLINE_SIZE <= site_offset):
        raise HookEngineError("hook site and trampoline storage overlap")
    if len(expected_original_words) != 2:
        raise HookEngineError("exactly two expected original instructions are required")
    if len(expected_trampoline) != TRAMPOLINE_SIZE:
        raise HookEngineError("expected_trampoline must contain exactly 16 bytes")

    actual_words = struct.unpack_from("<2I", data, site_offset)
    if actual_words != tuple(expected_original_words):
        raise HookEngineError(
            "original hook-site words mismatch: "
            f"found {[f'0x{x:08X}' for x in actual_words]}"
        )
    actual_trampoline = data[trampoline_offset:trampoline_offset + TRAMPOLINE_SIZE]
    if actual_trampoline != expected_trampoline:
        raise HookEngineError("trampoline storage does not match expected original bytes")

    # Decode every displaced instruction. Unknown encodings are rejected rather
    # than assumed relocatable; control transfers have delay-slot semantics.
    for index, word in enumerate(actual_words):
        try:
            ins = decode(word, site_pc + index * 4)
        except MipsDecodeError as exc:
            raise HookEngineError(f"cannot safely relocate instruction {index}: {exc}") from exc
        if ins.control_transfer:
            raise HookEngineError(
                f"cannot relocate control-transfer instruction {ins.mnemonic} at +{index * 4:#x}"
            )

    hook_words = (_encode_j(site_pc, hook_pc), 0)
    return_pc = site_pc + HOOK_SIZE
    trampoline_jump_pc = trampoline_pc + HOOK_SIZE
    if return_pc > MASK32 or trampoline_jump_pc > MASK32:
        raise HookEngineError("hook/trampoline address arithmetic overflows 32 bits")
    back_jump = _encode_j(trampoline_jump_pc, return_pc)
    trampoline_words = (actual_words[0], actual_words[1], back_jump, 0)
    return HookPatchPlan(
        site_offset, site_pc, hook_pc, trampoline_offset, trampoline_pc,
        tuple(actual_words), bytes(expected_trampoline), hook_words, trampoline_words,
    )


def apply_hook_patch(data: bytes, plan: HookPatchPlan) -> bytes:
    """Apply hook and trampoline atomically after revalidating all source bytes."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise HookEngineError("image must be bytes-like")
    if (isinstance(plan.site_offset, bool) or not isinstance(plan.site_offset, int)
            or plan.site_offset < 0 or plan.site_offset & 3
            or plan.site_offset + HOOK_SIZE > len(data)):
        raise HookEngineError("hook patch record has an invalid site offset")
    if (isinstance(plan.trampoline_offset, bool)
            or not isinstance(plan.trampoline_offset, int)
            or plan.trampoline_offset < 0 or plan.trampoline_offset & 3
            or plan.trampoline_offset + TRAMPOLINE_SIZE > len(data)):
        raise HookEngineError("hook patch record has an invalid trampoline offset")
    if not (plan.site_offset + HOOK_SIZE <= plan.trampoline_offset
            or plan.trampoline_offset + TRAMPOLINE_SIZE <= plan.site_offset):
        raise HookEngineError("hook patch record overlaps site and trampoline")
    current_words = struct.unpack_from("<2I", data, plan.site_offset)
    if current_words != plan.original_words:
        raise HookEngineError("hook site changed after planning; refusing patch")
    current_trampoline = bytes(data[plan.trampoline_offset:plan.trampoline_offset + TRAMPOLINE_SIZE])
    if current_trampoline != plan.expected_trampoline:
        raise HookEngineError("trampoline storage changed after planning; refusing patch")
    if len(plan.hook_words) != 2 or len(plan.trampoline_words) != 4:
        raise HookEngineError("malformed hook patch record")
    if plan.hook_words != (_encode_j(plan.site_pc, plan.hook_pc), 0):
        raise HookEngineError("hook patch words do not match the declared addresses")
    expected_back = _encode_j(plan.trampoline_pc + HOOK_SIZE, plan.site_pc + HOOK_SIZE)
    if plan.trampoline_words != (
        plan.original_words[0], plan.original_words[1], expected_back, 0
    ):
        raise HookEngineError("trampoline words do not match the declared addresses")

    output = bytearray(data)
    struct.pack_into("<2I", output, plan.site_offset, *plan.hook_words)
    struct.pack_into("<4I", output, plan.trampoline_offset, *plan.trampoline_words)
    return bytes(output)


def hook_plan_to_json(plan: HookPatchPlan) -> str:
    return json.dumps(plan.to_dict(), indent=2)

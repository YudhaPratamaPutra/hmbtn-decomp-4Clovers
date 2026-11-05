#!/usr/bin/env python3
"""Small, fail-closed MIPS-I/R3000 JAL and function-entry hook toolkit.

PS1 binaries are little-endian. This module only emits absolute J/JAL transfers
within the MIPS 256 MiB pseudo-direct region. Hook relocation is deliberately
limited to two ordinary, position-independent instructions.
"""
from __future__ import annotations

import argparse
import json
import struct
from dataclasses import asdict, dataclass
from pathlib import Path

MASK32 = 0xFFFFFFFF


class MipsPatchError(ValueError):
    pass


def _u32(value: int) -> int:
    return value & MASK32


def encode_jal(pc: int, target: int) -> int:
    """Encode JAL at pc; target must share the high 4 bits of pc+4."""
    if pc & 3 or target & 3:
        raise MipsPatchError("PC and target must be 4-byte aligned")
    if ((pc + 4) & 0xF0000000) != (target & 0xF0000000):
        raise MipsPatchError("JAL target is outside the 256 MiB pseudo-direct region")
    return 0x0C000000 | ((target >> 2) & 0x03FFFFFF)


def encode_j(pc: int, target: int) -> int:
    if pc & 3 or target & 3:
        raise MipsPatchError("PC and target must be 4-byte aligned")
    if ((pc + 4) & 0xF0000000) != (target & 0xF0000000):
        raise MipsPatchError("J target is outside the 256 MiB pseudo-direct region")
    return 0x08000000 | ((target >> 2) & 0x03FFFFFF)


def decode_jump(pc: int, instruction: int) -> dict:
    opcode = (instruction >> 26) & 0x3F
    if opcode not in (2, 3):
        raise MipsPatchError(f"instruction opcode {opcode} is not J/JAL")
    target = (((pc + 4) & 0xF0000000) | ((instruction & 0x03FFFFFF) << 2))
    return {"kind": "JAL" if opcode == 3 else "J", "pc": _u32(pc),
            "target": _u32(target), "instruction": _u32(instruction)}


def _is_control_or_pc_relative(word: int) -> bool:
    op = (word >> 26) & 0x3F
    if op in (1, 2, 3, 4, 5, 6, 7, 20, 21, 22, 23):
        return True  # REGIMM, J/JAL, conditional branches (incl. likely)
    if op in (16, 17, 18, 19):
        return ((word >> 21) & 0x1F) == 8  # COP branch
    if op == 0 and (word & 0x3F) in (8, 9):
        return True  # JR/JALR
    return False


def _pack_words(words: tuple[int, ...]) -> bytes:
    return struct.pack("<" + "I" * len(words), *(_u32(w) for w in words))


def _read_words(data: bytes, offset: int, count: int) -> tuple[int, ...]:
    end = offset + count * 4
    if offset < 0 or end > len(data) or offset & 3:
        raise MipsPatchError("instruction range is unaligned or outside the file")
    return struct.unpack_from("<" + "I" * count, data, offset)


@dataclass(frozen=True)
class HookPlan:
    site: int
    hook: int
    trampoline: int
    original_words: tuple[int, int]
    patch_words: tuple[int, int]
    trampoline_words: tuple[int, int, int, int]

    def to_json(self) -> str:
        obj = asdict(self)
        for key in ("original_words", "patch_words", "trampoline_words"):
            obj[key] = [f"0x{x:08X}" for x in obj[key]]
        for key in ("site", "hook", "trampoline"):
            obj[key] = f"0x{obj[key]:08X}"
        return json.dumps(obj, indent=2)


def make_hook_plan(site: int, hook: int, trampoline: int,
                   original_words: tuple[int, int]) -> HookPlan:
    """Plan a 2-word entry hook and a 2-word displaced-instruction trampoline."""
    if site & 3 or hook & 3 or trampoline & 3:
        raise MipsPatchError("site, hook, and trampoline must be 4-byte aligned")
    if len(original_words) != 2:
        raise MipsPatchError("exactly two original instructions are required")
    if any(_is_control_or_pc_relative(w) for w in original_words):
        raise MipsPatchError(
            "cannot relocate branch/jump instruction; choose a different hook site"
        )
    patch = (encode_j(site, hook), 0)  # J hook; NOP delay slot
    back_pc = trampoline + 8
    back_jump = encode_j(back_pc, site + 8)
    tramp = (original_words[0], original_words[1], back_jump, 0)
    return HookPlan(site, hook, trampoline, original_words, patch, tramp)


def apply_hook(data: bytes, file_offset: int, plan: HookPlan,
               expected_words: tuple[int, int]) -> tuple[bytes, bytes]:
    """Return (patched_image, trampoline_bytes); never mutates input."""
    actual = _read_words(data, file_offset, 2)
    if actual != expected_words or actual != plan.original_words:
        raise MipsPatchError(
            f"original-byte check failed: found {[hex(x) for x in actual]}"
        )
    patched = bytearray(data)
    patched[file_offset:file_offset + 8] = _pack_words(plan.patch_words)
    return bytes(patched), _pack_words(plan.trampoline_words)


def apply_jal(data: bytes, file_offset: int, pc: int, target: int,
              expected_word: int) -> bytes:
    actual = _read_words(data, file_offset, 1)[0]
    if actual != expected_word:
        raise MipsPatchError(
            f"original-byte check failed: found 0x{actual:08X}, "
            f"expected 0x{expected_word:08X}"
        )
    patched = bytearray(data)
    struct.pack_into("<I", patched, file_offset, encode_jal(pc, target))
    return bytes(patched)


def _int(s: str) -> int:
    return int(s, 0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("jal-encode")
    p.add_argument("--pc", required=True, type=_int)
    p.add_argument("--target", required=True, type=_int)
    p = sub.add_parser("jump-decode")
    p.add_argument("--pc", required=True, type=_int)
    p.add_argument("--word", required=True, type=_int)
    p = sub.add_parser("hook-plan")
    p.add_argument("--site", required=True, type=_int)
    p.add_argument("--hook", required=True, type=_int)
    p.add_argument("--trampoline", required=True, type=_int)
    p.add_argument("--word0", required=True, type=_int)
    p.add_argument("--word1", required=True, type=_int)
    args = parser.parse_args()
    if args.cmd == "jal-encode":
        print(f"0x{encode_jal(args.pc, args.target):08X}")
    elif args.cmd == "jump-decode":
        print(json.dumps(decode_jump(args.pc, args.word), indent=2))
    else:
        plan = make_hook_plan(args.site, args.hook, args.trampoline,
                              (args.word0, args.word1))
        print(plan.to_json())


if __name__ == "__main__":
    main()

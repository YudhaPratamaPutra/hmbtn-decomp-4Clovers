"""Sequential MIPS-I analysis for an explicitly mapped overlay image.

The scanner decodes aligned words in a caller-selected range. It reports direct
control-flow references only; it does not infer code/data boundaries or create
patch targets.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Any

from .core import MipsDecodeError, decode


class MipsAnalysisError(ValueError):
    pass


@dataclass(frozen=True)
class MipsAnalysis:
    base_address: int
    start_offset: int
    end_offset: int
    decoded_count: int
    undecoded_count: int
    instructions: tuple[dict[str, Any], ...]
    references: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "base_address": f"0x{self.base_address:08X}",
            "start_offset": f"0x{self.start_offset:X}",
            "end_offset": f"0x{self.end_offset:X}",
            "decoded_count": self.decoded_count,
            "undecoded_count": self.undecoded_count,
            "instructions": list(self.instructions),
            "references": list(self.references),
        }


def analyze_mips_image(
    image: bytes, base_address: int, *, start_offset: int = 0,
    end_offset: int | None = None,
) -> MipsAnalysis:
    """Decode every aligned word in the explicit range and collect direct refs."""
    if not isinstance(image, (bytes, bytearray, memoryview)):
        raise MipsAnalysisError("image must be bytes-like")
    image = bytes(image)
    for value, name in ((base_address, "base_address"),
                        (start_offset, "start_offset")):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise MipsAnalysisError(f"{name} must be a non-negative integer")
    if base_address > 0xFFFFFFFF or base_address & 3:
        raise MipsAnalysisError("base_address must be an aligned unsigned 32-bit address")
    if end_offset is None:
        end = len(image) & ~3
    else:
        if isinstance(end_offset, bool) or not isinstance(end_offset, int) or end_offset < 0:
            raise MipsAnalysisError("end_offset must be a non-negative integer")
        end = end_offset
    if start_offset & 3 or end & 3 or end < start_offset or end > len(image):
        raise MipsAnalysisError("analysis range must be aligned and inside the image")
    if end > start_offset and base_address + end - 4 > 0xFFFFFFFF:
        raise MipsAnalysisError("analysis mapping exceeds the 32-bit address space")

    instructions = []
    references = []
    undecoded = 0
    for offset in range(start_offset, end, 4):
        word = struct.unpack_from("<I", image, offset)[0]
        pc = base_address + offset
        try:
            ins = decode(word, pc)
        except MipsDecodeError as exc:
            undecoded += 1
            instructions.append({
                "file_offset": f"0x{offset:X}",
                "pc": f"0x{pc:08X}",
                "word": f"0x{word:08X}",
                "decoded": False,
                "error": str(exc),
            })
            continue
        row = {
            "file_offset": f"0x{offset:X}",
            "pc": f"0x{pc:08X}",
            "word": f"0x{word:08X}",
            "decoded": True,
            "mnemonic": ins.mnemonic,
            "rs": ins.rs,
            "rt": ins.rt,
            "rd": ins.rd,
            "immediate": f"0x{ins.immediate:04X}",
            "signed_immediate": ins.signed_immediate,
            "control_transfer": ins.control_transfer,
        }
        if ins.branch_target is not None:
            row["branch_target"] = f"0x{ins.branch_target:08X}"
            references.append({
                "source_pc": f"0x{pc:08X}",
                "kind": "branch",
                "target": f"0x{ins.branch_target:08X}",
            })
        if ins.jump_target is not None:
            row["jump_target"] = f"0x{ins.jump_target:08X}"
            references.append({
                "source_pc": f"0x{pc:08X}",
                "kind": "jal" if ins.mnemonic == "jal" else "jump",
                "target": f"0x{ins.jump_target:08X}",
            })
        instructions.append(row)

    return MipsAnalysis(
        base_address, start_offset, end, len(instructions) - undecoded,
        undecoded, tuple(instructions), tuple(references),
    )

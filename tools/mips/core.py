"""Strict MIPS-I/R3000 instruction field decoder and basic encoders.

Words are represented as host integers. Binary I/O for PS1 images remains
little-endian and is handled by the patching layer.
"""
from __future__ import annotations

from dataclasses import dataclass

MASK32 = 0xFFFFFFFF


class MipsDecodeError(ValueError):
    """Raised when an instruction word or encoding field is invalid."""


SPECIAL = {
    0x00: "sll", 0x02: "srl", 0x03: "sra",
    0x04: "sllv", 0x06: "srlv", 0x07: "srav",
    0x08: "jr", 0x09: "jalr", 0x0C: "syscall", 0x0D: "break",
    0x10: "mfhi", 0x11: "mthi", 0x12: "mflo", 0x13: "mtlo",
    0x18: "mult", 0x19: "multu", 0x1A: "div", 0x1B: "divu",
    0x20: "add", 0x21: "addu", 0x22: "sub", 0x23: "subu",
    0x24: "and", 0x25: "or", 0x26: "xor", 0x27: "nor",
    0x2A: "slt", 0x2B: "sltu",
}
REGIMM = {0: "bltz", 1: "bgez", 16: "bltzal", 17: "bgezal"}
OPCODES = {
    2: "j", 3: "jal", 4: "beq", 5: "bne", 6: "blez", 7: "bgtz",
    8: "addi", 9: "addiu", 10: "slti", 11: "sltiu",
    12: "andi", 13: "ori", 14: "xori", 15: "lui",
    32: "lb", 33: "lh", 34: "lwl", 35: "lw", 36: "lbu",
    37: "lhu", 38: "lwr", 40: "sb", 41: "sh", 42: "swl",
    43: "sw", 46: "swr",
}


def _field(value: int, bits: int, name: str) -> int:
    if not isinstance(value, int) or value < 0 or value >= (1 << bits):
        raise MipsDecodeError(f"{name} must fit in an unsigned {bits}-bit field")
    return value


def _signed16(value: int) -> int:
    value &= 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


@dataclass(frozen=True)
class Instruction:
    word: int
    pc: int
    opcode: int
    mnemonic: str
    rs: int
    rt: int
    rd: int
    shamt: int
    funct: int
    immediate: int
    signed_immediate: int
    target_index: int
    branch_target: int | None
    jump_target: int | None
    control_transfer: bool
    delay_slot: bool


def decode(word: int, pc: int = 0) -> Instruction:
    """Decode a MIPS-I word; unknown/reserved encodings fail closed."""
    if not isinstance(word, int) or word < 0 or word > MASK32:
        raise MipsDecodeError("instruction word must be an unsigned 32-bit integer")
    if pc & 3:
        raise MipsDecodeError("PC must be 4-byte aligned")

    op = (word >> 26) & 0x3F
    rs, rt = (word >> 21) & 31, (word >> 16) & 31
    rd, shamt, funct = (word >> 11) & 31, (word >> 6) & 31, word & 63
    imm, index = word & 0xFFFF, word & 0x03FFFFFF
    branch_target = jump_target = None
    control = False

    if op == 0:
        mnemonic = SPECIAL.get(funct)
        if mnemonic is None:
            raise MipsDecodeError(f"unsupported/reserved SPECIAL funct 0x{funct:02X}")
        if mnemonic in ("jr", "jalr"):
            control = True
    elif op == 1:
        mnemonic = REGIMM.get(rt)
        if mnemonic is None:
            raise MipsDecodeError(f"unsupported/reserved REGIMM rt 0x{rt:02X}")
        control = True
        branch_target = (pc + 4 + (_signed16(imm) << 2)) & MASK32
    elif op in (16, 17, 18):
        cop = {16: "cop0", 17: "cop1", 18: "cop2"}[op]
        if rs == 8:
            mnemonic = cop + "_bc" + ("t" if rt & 1 else "f")
            control = True
            branch_target = (pc + 4 + (_signed16(imm) << 2)) & MASK32
        elif rs == 0:
            mnemonic = cop + "_mfc"
        elif rs == 2:
            mnemonic = cop + "_cfc"
        elif rs == 4:
            mnemonic = cop + "_mtc"
        elif rs == 6:
            mnemonic = cop + "_ctc"
        elif rs >= 16:
            mnemonic = cop + "_op"
        else:
            raise MipsDecodeError(f"unsupported {cop.upper()} rs field {rs}")
    elif op == 19:
        raise MipsDecodeError("COP3 is not implemented for the PS1 R3000 core")
    else:
        mnemonic = OPCODES.get(op)
        if mnemonic is None:
            raise MipsDecodeError(f"unsupported/reserved opcode 0x{op:02X}")
        if op in (2, 3):
            control = True
            jump_target = (((pc + 4) & 0xF0000000) | (index << 2)) & MASK32
        elif op in (4, 5, 6, 7):
            control = True
            branch_target = (pc + 4 + (_signed16(imm) << 2)) & MASK32

    return Instruction(
        word=word, pc=pc & MASK32, opcode=op, mnemonic=mnemonic,
        rs=rs, rt=rt, rd=rd, shamt=shamt, funct=funct,
        immediate=imm, signed_immediate=_signed16(imm), target_index=index,
        branch_target=branch_target, jump_target=jump_target,
        control_transfer=control, delay_slot=control,
    )


def encode_r(rs: int, rt: int, rd: int, shamt: int, funct: int) -> int:
    return ((_field(rs, 5, "rs") << 21) | (_field(rt, 5, "rt") << 16)
            | (_field(rd, 5, "rd") << 11) | (_field(shamt, 5, "shamt") << 6)
            | _field(funct, 6, "funct"))


def encode_i(opcode: int, rs: int, rt: int, immediate: int) -> int:
    _field(opcode, 6, "opcode")
    _field(rs, 5, "rs")
    _field(rt, 5, "rt")
    if not isinstance(immediate, int) or not -0x8000 <= immediate <= 0xFFFF:
        raise MipsDecodeError("immediate must fit signed or unsigned 16-bit range")
    return (opcode << 26) | (rs << 21) | (rt << 16) | (immediate & 0xFFFF)


def encode_j(opcode: int, pc: int, target: int) -> int:
    if opcode not in (2, 3):
        raise MipsDecodeError("J-format opcode must be 2 (J) or 3 (JAL)")
    if pc & 3 or target & 3:
        raise MipsDecodeError("PC and target must be 4-byte aligned")
    if ((pc + 4) & 0xF0000000) != (target & 0xF0000000):
        raise MipsDecodeError("target is outside the PC+4 pseudo-direct region")
    return (opcode << 26) | ((target >> 2) & 0x03FFFFFF)


def encode_branch(opcode: int, pc: int, target: int, rs: int, rt: int) -> int:
    """Encode BEQ/BNE/BLEZ/BGTZ with a signed word displacement."""
    if opcode not in (4, 5, 6, 7):
        raise MipsDecodeError("branch opcode must be BEQ/BNE/BLEZ/BGTZ")
    if pc & 3 or target & 3:
        raise MipsDecodeError("PC and branch target must be 4-byte aligned")
    displacement = (target - (pc + 4)) // 4
    if not -0x8000 <= displacement <= 0x7FFF:
        raise MipsDecodeError("branch target is outside signed 16-bit displacement range")
    return encode_i(opcode, rs, rt, displacement)

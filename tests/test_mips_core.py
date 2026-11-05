import unittest

from tools.mips.core import (
    MipsDecodeError, decode, encode_branch, encode_i, encode_j, encode_r,
)


class MipsCoreTests(unittest.TestCase):
    def test_decode_r_type_fields(self):
        word = encode_r(rs=0, rt=29, rd=29, shamt=0, funct=0x21)
        ins = decode(word, 0x80010000)
        self.assertEqual(ins.mnemonic, "addu")
        self.assertEqual((ins.rs, ins.rt, ins.rd), (0, 29, 29))
        self.assertFalse(ins.control_transfer)

    def test_decode_signed_immediate(self):
        ins = decode(encode_i(9, 29, 29, -24), 0x80010000)
        self.assertEqual(ins.mnemonic, "addiu")
        self.assertEqual(ins.immediate, 0xFFE8)
        self.assertEqual(ins.signed_immediate, -24)

    def test_decode_branch_target_and_delay_slot(self):
        pc = 0x80010000
        word = encode_branch(4, pc, 0x80010020, 8, 0)
        ins = decode(word, pc)
        self.assertEqual(ins.mnemonic, "beq")
        self.assertEqual(ins.branch_target, 0x80010020)
        self.assertTrue(ins.control_transfer)
        self.assertTrue(ins.delay_slot)

    def test_decode_jump_target_region(self):
        pc, target = 0x80010000, 0x80023450
        ins = decode(encode_j(3, pc, target), pc)
        self.assertEqual(ins.mnemonic, "jal")
        self.assertEqual(ins.jump_target, target)

    def test_regimm_link_branch(self):
        ins = decode(encode_i(1, 4, 16, -2), 0x80010000)
        self.assertEqual(ins.mnemonic, "bltzal")
        self.assertTrue(ins.control_transfer)

    def test_cop0_rfe_classification(self):
        ins = decode(0x42000010, 0x80010000)
        self.assertEqual(ins.mnemonic, "cop0_op")

    def test_unknown_instruction_rejected(self):
        with self.assertRaises(MipsDecodeError):
            decode(0xFFFFFFFF, 0x80010000)

    def test_encode_field_overflow_rejected(self):
        with self.assertRaises(MipsDecodeError):
            encode_r(32, 0, 0, 0, 0)

    def test_jump_region_rejected(self):
        with self.assertRaises(MipsDecodeError):
            encode_j(3, 0x8FFFFFFC, 0x80000000)

    def test_branch_range_rejected(self):
        with self.assertRaises(MipsDecodeError):
            encode_branch(4, 0x80000000, 0x80100000, 1, 2)


if __name__ == "__main__":
    unittest.main()

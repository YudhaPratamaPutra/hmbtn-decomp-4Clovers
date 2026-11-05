import unittest
from tools.mips_auto_integrator import (
    MipsPatchError, encode_jal, decode_jump, make_hook_plan, apply_hook,
    apply_jal,
)


class MipsIntegratorTests(unittest.TestCase):
    def test_jal_round_trip(self):
        word = encode_jal(0x80010000, 0x80023450)
        self.assertEqual(word, 0x0C008D14)
        self.assertEqual(decode_jump(0x80010000, word)["target"], 0x80023450)
        self.assertEqual(decode_jump(0x80010000, word)["kind"], "JAL")

    def test_jump_region_rejected(self):
        with self.assertRaises(MipsPatchError):
            encode_jal(0x8FFFFFFC, 0x80000000)

    def test_hook_and_trampoline(self):
        original = (0x27BDFFE8, 0xAFBF0010)  # addiu sp,sp,-24; sw ra,16(sp)
        plan = make_hook_plan(0x80012000, 0x80024000, 0x80030000, original)
        image = b"\xAA" * 16 + __import__("struct").pack("<II", *original) + b"\xBB" * 8
        patched, trampoline = apply_hook(image, 16, plan, original)
        self.assertEqual(len(patched), len(image))
        self.assertEqual(__import__("struct").unpack_from("<II", patched, 16),
                         plan.patch_words)
        self.assertEqual(len(trampoline), 16)

    def test_reject_branch_in_displaced_words(self):
        with self.assertRaises(MipsPatchError):
            make_hook_plan(0x80012000, 0x80024000, 0x80030000,
                           (0x10000001, 0x00000000))

    def test_jal_patch_success(self):
        import struct
        original = 0x00000000
        image = struct.pack("<II", original, 0x00000000)
        patched = apply_jal(image, 0, 0x80010000, 0x80020000, original)
        self.assertEqual(struct.unpack_from("<I", patched, 0)[0],
                         encode_jal(0x80010000, 0x80020000))
        self.assertEqual(len(patched), len(image))

    def test_expected_word_guard(self):
        with self.assertRaises(MipsPatchError):
            apply_jal(b"\0" * 8, 0, 0x80010000, 0x80020000, 0x12345678)


if __name__ == "__main__":
    unittest.main()

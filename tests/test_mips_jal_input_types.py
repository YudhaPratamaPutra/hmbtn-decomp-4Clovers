import unittest

from tools.mips.jal import (
    JalEngineError,
    JalPatch,
    apply_jal_patches,
    plan_jal_patch,
    scan_jal,
)


class JalInputTypeTests(unittest.TestCase):
    def test_scan_rejects_boolean_base_address(self):
        with self.assertRaisesRegex(JalEngineError, "base_address must be an integer"):
            scan_jal(b"\x00" * 8, False)

    def test_scan_rejects_boolean_range_offset(self):
        with self.assertRaisesRegex(JalEngineError, "start_offset must be an integer"):
            scan_jal(b"\x00" * 8, 0x80010000, start_offset=False)

    def test_plan_rejects_boolean_file_offset(self):
        with self.assertRaisesRegex(JalEngineError, "file_offset must be an integer"):
            plan_jal_patch(
                b"\x00" * 8,
                False,
                0x80010000,
                0x80020000,
                expected_word=0,
            )

    def test_apply_rejects_boolean_patch_offset(self):
        patch = JalPatch(
            file_offset=False,
            base_address=0x80010000,
            pc=0x80010000,
            old_target=0x80010000,
            new_target=0x80020000,
            expected_word=0x0C004000,
            replacement_word=0x0C008000,
        )
        with self.assertRaisesRegex(JalEngineError, "patch file_offset must be an integer"):
            apply_jal_patches(b"\x00" * 8, [patch])


if __name__ == "__main__":
    unittest.main()

import struct
import unittest

from tools.mips.jal import (
    JalEngineError, apply_jal_patches, plan_jal_patch, scan_jal,
)


class JalEngineTests(unittest.TestCase):
    BASE = 0x80010000

    def test_scan_finds_jal_and_resolves_runtime_target(self):
        words = [0, 0x0C008D14, 0x08008D14, 0x0C008D14]
        image = struct.pack("<4I", *words)
        found = scan_jal(image, self.BASE)
        self.assertEqual([x.file_offset for x in found], [4, 12])
        self.assertEqual([x.pc for x in found], [0x80010004, 0x8001000C])
        self.assertEqual([x.target for x in found], [0x80023450, 0x80023450])

    def test_scan_target_filter_and_range(self):
        image = struct.pack("<4I", 0x0C008D14, 0, 0x0C008D14, 0x0C008D14)
        found = scan_jal(image, self.BASE, start_offset=4, end_offset=12,
                         target=0x80023450)
        self.assertEqual([x.file_offset for x in found], [8])

    def test_scan_rejects_unaligned_mapping_or_range(self):
        with self.assertRaises(JalEngineError):
            scan_jal(b"\0" * 8, self.BASE + 1)
        with self.assertRaises(JalEngineError):
            scan_jal(b"\0" * 8, self.BASE, start_offset=2)

    def test_plan_and_apply_guarded_patch(self):
        original = 0x0C008D14
        image = struct.pack("<II", original, 0x12345678)
        patch = plan_jal_patch(image, 0, self.BASE, 0x80030000,
                               expected_word=original, expected_target=0x80023450)
        result = apply_jal_patches(image, [patch])
        self.assertEqual(struct.unpack_from("<I", result)[0], 0x0C00C000)
        self.assertEqual(result[4:], image[4:])
        self.assertEqual(image[:4], struct.pack("<I", original))

    def test_wrong_original_word_rejected(self):
        image = struct.pack("<I", 0x0C008D14)
        with self.assertRaises(JalEngineError):
            plan_jal_patch(image, 0, self.BASE, 0x80030000,
                           expected_word=0x0C008D15)

    def test_wrong_expected_target_rejected(self):
        image = struct.pack("<I", 0x0C008D14)
        with self.assertRaises(JalEngineError):
            plan_jal_patch(image, 0, self.BASE, 0x80030000,
                           expected_word=0x0C008D14, expected_target=0x80024000)

    def test_batch_is_atomic_on_late_mismatch(self):
        image = struct.pack("<2I", 0x0C008D14, 0x0C008D14)
        first = plan_jal_patch(image, 0, self.BASE, 0x80030000,
                               expected_word=0x0C008D14)
        second = plan_jal_patch(image, 4, self.BASE, 0x80030000,
                                expected_word=0x0C008D14)
        changed = bytearray(image)
        struct.pack_into("<I", changed, 4, 0)
        with self.assertRaises(JalEngineError):
            apply_jal_patches(bytes(changed), [first, second])
        self.assertEqual(bytes(changed), struct.pack("<II", 0x0C008D14, 0))

    def test_duplicate_patch_offset_rejected(self):
        image = struct.pack("<I", 0x0C008D14)
        patch = plan_jal_patch(image, 0, self.BASE, 0x80030000,
                               expected_word=0x0C008D14)
        with self.assertRaises(JalEngineError):
            apply_jal_patches(image, [patch, patch])

    def test_target_outside_pseudodirect_region_rejected(self):
        image = struct.pack("<I", 0x0C008D14)
        with self.assertRaises(JalEngineError):
            plan_jal_patch(image, 0, 0x8FFFFFFC, 0x80000000,
                           expected_word=0x0C008D14)


if __name__ == "__main__":
    unittest.main()

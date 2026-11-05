import struct
import unittest

from tools.mips.integration import IntegrationPlan
from tools.mips.validation import ValidationError, validate_integrated_image


class ValidationEngineTests(unittest.TestCase):
    def test_valid_jal_patch_and_unchanged_bytes(self):
        original = bytearray(b"\x00" * 0x20)
        struct.pack_into("<I", original, 4, 0x0C000000)
        output = bytearray(original)
        struct.pack_into("<I", output, 4, 0x0C000100)
        plan = IntegrationPlan(
            overlay="11_GF_FARM",
            image_sha256=__import__("hashlib").sha256(original).hexdigest(),
            base_address=0x80010000,
            entries=({
                "id": "call-a", "type": "jal",
                "patch": {
                    "file_offset": "0x4",
                    "expected_word": "0x0C000000",
                    "replacement_word": "0x0C000100",
                },
            },),
        )
        report = validate_integrated_image(bytes(original), bytes(output), plan)
        self.assertEqual(report.changed_ranges, ((4, 8),))
        self.assertEqual(report.authorized_ranges, ((4, 8, "call-a"),))

    def test_rejects_modification_outside_patch_ranges(self):
        original = b"\x00" * 0x20
        output = bytearray(original)
        output[0x1F] = 1
        plan = IntegrationPlan(
            "11_GF_FARM", __import__("hashlib").sha256(original).hexdigest(),
            0x80010000, (),
        )
        with self.assertRaisesRegex(ValidationError, "outside authorized"):
            validate_integrated_image(original, bytes(output), plan)

    def test_rejects_wrong_replacement_word(self):
        original = bytearray(b"\x00" * 0x20)
        struct.pack_into("<I", original, 4, 0x0C000000)
        output = bytearray(original)
        struct.pack_into("<I", output, 4, 0x0C000200)
        plan = IntegrationPlan(
            "11_GF_FARM", __import__("hashlib").sha256(original).hexdigest(),
            0x80010000, ({
                "id": "call-a", "type": "jal",
                "patch": {
                    "file_offset": "0x4",
                    "expected_word": "0x0C000000",
                    "replacement_word": "0x0C000100",
                },
            },),
        )
        with self.assertRaisesRegex(ValidationError, "do not match"):
            validate_integrated_image(original, bytes(output), plan)

    def test_rejects_image_size_change(self):
        original = b"\x00" * 8
        plan = IntegrationPlan(
            "11_GF_FARM", __import__("hashlib").sha256(original).hexdigest(),
            0x80010000, (),
        )
        with self.assertRaisesRegex(ValidationError, "image size changed"):
            validate_integrated_image(original, original + b"\x00", plan)

    def test_rejects_original_image_hash_mismatch(self):
        original = b"\x00" * 8
        plan = IntegrationPlan("11_GF_FARM", "0" * 64, 0x80010000, ())
        with self.assertRaisesRegex(ValidationError, "SHA-256"):
            validate_integrated_image(original, original, plan)

    def test_empty_plan_requires_identical_images(self):
        original = b"\x12\x34\x56\x78"
        plan = IntegrationPlan(
            "11_GF_FARM", __import__("hashlib").sha256(original).hexdigest(),
            0x80010000, (),
        )
        report = validate_integrated_image(original, original, plan)
        self.assertEqual(report.changed_ranges, ())
        self.assertEqual(report.authorized_ranges, ())


if __name__ == "__main__":
    unittest.main()

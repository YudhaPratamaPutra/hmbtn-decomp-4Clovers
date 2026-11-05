import unittest

from tools.mips.integration import IntegrationError, _integer, build_integration_plan


class IntegrationInputValidationTests(unittest.TestCase):
    def test_integer_accepts_integer_and_hex_string(self):
        self.assertEqual(_integer(4, "offset"), 4)
        self.assertEqual(_integer("0x10", "offset"), 16)

    def test_integer_rejects_float_instead_of_truncating(self):
        with self.assertRaisesRegex(IntegrationError, "must be an integer"):
            _integer(4.9, "offset")

    def test_integer_rejects_boolean(self):
        with self.assertRaisesRegex(IntegrationError, "must be an integer"):
            _integer(True, "offset")

    def test_plan_rejects_non_bytes_image_input(self):
        with self.assertRaisesRegex(IntegrationError, "image must be bytes-like"):
            build_integration_plan(
                4,
                base_address=0x80010000,
                overlay="11_GF_FARM",
                registry_path="unused-registry.json",
                map_path="unused.map",
            )


if __name__ == "__main__":
    unittest.main()

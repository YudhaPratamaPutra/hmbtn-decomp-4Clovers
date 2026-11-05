import json
import struct
import tempfile
import unittest
from pathlib import Path

from tools.mips.integration import (
    IntegrationError, apply_integration_plan, build_integration_plan,
)


class IntegrationPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.registry = self.root / "hooks.json"
        self.map_file = self.root / "program.map"
        self.base = 0x80010000

    def tearDown(self):
        self.temp.cleanup()

    def write_inputs(self, hooks, map_text):
        self.registry.write_text(json.dumps({
            "schema_version": 1, "module": "11_GF_FARM", "hooks": hooks,
        }), encoding="utf-8")
        self.map_file.write_text(map_text, encoding="utf-8")

    def run_plan(self, image):
        return build_integration_plan(
            bytes(image), base_address=self.base, overlay="11_GF_FARM",
            registry_path=self.registry, map_path=self.map_file,
        )

    def test_jal_registry_plan_and_apply(self):
        image = bytearray(b"\x00" * 0x40)
        struct.pack_into("<I", image, 0x10, 0x0C006000)
        self.write_inputs([{
            "id": "farm-call", "type": "jal", "site_symbol": "farm_callsite",
            "file_offset": "0x10", "expected_word": "0x0C006000",
            "expected_target": "0x80018000", "target_symbol": "farm_mod_entry",
        }], "0x80010010 farm_callsite\n0x80020000 farm_mod_entry\n")
        plan = self.run_plan(image)
        self.assertEqual(plan.to_dict()["entry_count"], 1)
        patched = apply_integration_plan(
            bytes(image), plan, base_address=self.base, overlay="11_GF_FARM",
            registry_path=self.registry, map_path=self.map_file,
        )
        self.assertNotEqual(patched, bytes(image))
        self.assertEqual(len(patched), len(image))

    def test_hook_registry_plan_and_apply(self):
        image = bytearray(b"\xAA" * 0x60)
        struct.pack_into("<2I", image, 0x10, 0x27BDFFE8, 0xAFBF0010)
        image[0x30:0x40] = b"\xCC" * 16
        self.write_inputs([{
            "id": "farm-entry", "type": "hook", "site_symbol": "farm_entry",
            "site_offset": "0x10", "hook_symbol": "farm_mod_entry",
            "trampoline_symbol": "farm_trampoline", "trampoline_offset": "0x30",
            "expected_words": ["0x27BDFFE8", "0xAFBF0010"],
            "expected_trampoline": "CC" * 16,
        }], "0x80010010 farm_entry\n0x80012000 farm_mod_entry\n"
             "0x80010030 farm_trampoline\n"
             "0x80010030 __mips_trampoline_start\n"
             "0x80010040 __mips_trampoline_end\n")
        plan = self.run_plan(image)
        patched = apply_integration_plan(
            bytes(image), plan, base_address=self.base, overlay="11_GF_FARM",
            registry_path=self.registry, map_path=self.map_file,
        )
        self.assertNotEqual(patched[0x10:0x18], bytes(image[0x10:0x18]))
        self.assertNotEqual(patched[0x30:0x40], bytes(image[0x30:0x40]))

    def test_hook_trampoline_offset_must_match_linker_symbol(self):
        image = bytearray(b"\xAA" * 0x60)
        struct.pack_into("<2I", image, 0x10, 0x27BDFFE8, 0xAFBF0010)
        image[0x30:0x40] = b"\xCC" * 16
        self.write_inputs([{
            "id": "farm-entry", "type": "hook", "site_symbol": "farm_entry",
            "site_offset": "0x10", "hook_symbol": "farm_mod_entry",
            "trampoline_symbol": "farm_trampoline", "trampoline_offset": "0x34",
            "expected_words": ["0x27BDFFE8", "0xAFBF0010"],
            "expected_trampoline": "CC" * 16,
        }], "0x80010010 farm_entry\n0x80012000 farm_mod_entry\n"
             "0x80010030 farm_trampoline\n"
             "0x80010030 __mips_trampoline_start\n"
             "0x80010040 __mips_trampoline_end\n")
        with self.assertRaisesRegex(IntegrationError, "does not equal trampoline symbol address"):
            self.run_plan(image)

    def test_missing_symbol_fails_closed(self):
        self.write_inputs([{
            "id": "bad", "type": "jal", "site_symbol": "missing",
            "file_offset": "0x10", "expected_word": "0x0C006000",
            "expected_target": "0x80018000", "target_symbol": "also_missing",
        }], "")
        with self.assertRaises(IntegrationError):
            self.run_plan(b"\x00" * 0x40)

    def test_site_symbol_and_file_mapping_must_agree(self):
        self.write_inputs([{
            "id": "bad-map", "type": "jal", "site_symbol": "farm_callsite",
            "file_offset": "0x14", "expected_word": "0x0C006000",
            "expected_target": "0x80018000", "target_symbol": "farm_mod_entry",
        }], "0x80010010 farm_callsite\n0x80020000 farm_mod_entry\n")
        with self.assertRaises(IntegrationError):
            self.run_plan(b"\x00" * 0x40)

    def test_registry_unknown_fields_rejected(self):
        self.write_inputs([{
            "id": "bad", "type": "jal", "site_symbol": "farm_callsite",
            "file_offset": "0x10", "expected_word": "0x0C006000",
            "expected_target": "0x80018000", "target_symbol": "farm_mod_entry",
            "guess_free_space": True,
        }], "0x80010010 farm_callsite\n0x80020000 farm_mod_entry\n")
        with self.assertRaises(IntegrationError):
            self.run_plan(b"\x00" * 0x40)

    def test_empty_registry_is_noop_plan(self):
        self.write_inputs([], "")
        image = b"\x12\x34\x56\x78"
        plan = self.run_plan(image)
        output = apply_integration_plan(
            image, plan, base_address=self.base, overlay="11_GF_FARM",
            registry_path=self.registry, map_path=self.map_file,
        )
        self.assertEqual(output, image)
        self.assertEqual(plan.entries, ())

    def test_stale_image_rejected(self):
        image = bytearray(b"\x00" * 0x40)
        struct.pack_into("<I", image, 0x10, 0x0C006000)
        self.write_inputs([{
            "id": "farm-call", "type": "jal", "site_symbol": "farm_callsite",
            "file_offset": "0x10", "expected_word": "0x0C006000",
            "expected_target": "0x80018000", "target_symbol": "farm_mod_entry",
        }], "0x80010010 farm_callsite\n0x80020000 farm_mod_entry\n")
        plan = self.run_plan(image)
        changed = bytearray(image)
        changed[0] ^= 1
        with self.assertRaises(IntegrationError):
            apply_integration_plan(
                bytes(changed), plan, base_address=self.base, overlay="11_GF_FARM",
                registry_path=self.registry, map_path=self.map_file,
            )


if __name__ == "__main__":
    unittest.main()

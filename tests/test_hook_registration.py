import struct
import tempfile
import unittest
from pathlib import Path

from tools.mips.registration import (
    HookRegistrationError,
    generate_hook_registry,
    write_hook_registry,
)
from tools.mips.integration import build_integration_plan, apply_integration_plan
from tools.mips.validation import validate_integrated_image


class HookRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.overlay = self.root / "11_GF_FARM"
        (self.overlay / "mod").mkdir(parents=True)
        self.image_path = self.root / "11_GF_FARM.bin"
        self.map_path = self.root / "program.map"
        self.base = 0x800B7E20
        image = bytearray(128)
        struct.pack_into("<2I", image, 16, 0x27BDFFF0, 0xAFBF000C)
        self.image_path.write_bytes(image)
        self.map_path.write_text(
            f"0x{self.base + 16:08X} farm_tile_state\n"
            f"0x{self.base + 64:08X} mod_farm_tile_state\n"
            f"0x{self.base + 96:08X} crop_pass_trampoline\n"
            f"0x{self.base + 16:08X} overlap_trampoline\n"
            f"0x{self.base + 96:08X} __mips_trampoline_start_11_GF_FARM\n"
            f"0x{self.base + 112:08X} __mips_trampoline_end_11_GF_FARM\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _source(self, metadata):
        (self.overlay / "mod" / "crop.c").write_text(
            f"/* MIPS_AUTO_HOOK: {metadata} */\n"
            "void mod_farm_tile_state(void) { }\n",
            encoding="utf-8",
        )

    def test_generates_registry_from_map_and_exact_image_bytes(self):
        self._source(
            '{"id":"crop-pass","type":"hook","site_symbol":"farm_tile_state",'
            '"trampoline_symbol":"crop_pass_trampoline"}'
        )
        registry = generate_hook_registry(
            self.overlay, map_path=self.map_path, image_path=self.image_path,
            base_address=self.base,
        )
        self.assertEqual(registry["module"], "11_GF_FARM")
        self.assertEqual(len(registry["hooks"]), 1)
        entry = registry["hooks"][0]
        self.assertEqual(entry["site_offset"], "0x10")
        self.assertEqual(entry["hook_symbol"], "mod_farm_tile_state")
        self.assertEqual(entry["trampoline_offset"], "0x60")
        self.assertEqual(entry["expected_words"], ["0x27BDFFF0", "0xAFBF000C"])
        self.assertEqual(entry["expected_trampoline"], "00" * 16)

    def test_requires_trampoline_symbol_declaration(self):
        self._source(
            '{"id":"crop-pass","type":"hook","site_symbol":"farm_tile_state",'
            '"trampoline_symbol":"not_in_map"}'
        )
        with self.assertRaises(HookRegistrationError):
            generate_hook_registry(
                self.overlay, map_path=self.map_path, image_path=self.image_path,
                base_address=self.base,
            )

    def test_rejects_missing_target_symbol(self):
        self._source(
            '{"id":"crop-pass","type":"hook","site_symbol":"not_in_map",'
            '"trampoline_symbol":"missing_trampoline"}'
        )
        with self.assertRaises(HookRegistrationError):
            generate_hook_registry(
                self.overlay, map_path=self.map_path, image_path=self.image_path,
                base_address=self.base,
            )

    def test_rejects_trampoline_section_outside_image(self):
        self._source(
            '{"id":"crop-pass","type":"hook","site_symbol":"farm_tile_state",'
            '"trampoline_symbol":"crop_pass_trampoline"}'
        )
        self.map_path.write_text(
            f"0x{self.base + 16:08X} farm_tile_state\n"
            f"0x{self.base + 64:08X} mod_farm_tile_state\n"
            f"0x{self.base + 96:08X} crop_pass_trampoline\n"
            f"0x{self.base + 128:08X} __mips_trampoline_start_11_GF_FARM\n"
            f"0x{self.base + 144:08X} __mips_trampoline_end_11_GF_FARM\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(HookRegistrationError, "outside the supplied image mapping"):
            generate_hook_registry(
                self.overlay, map_path=self.map_path, image_path=self.image_path,
                base_address=self.base,
            )

    def test_rejects_reversed_trampoline_section_bounds(self):
        self._source(
            '{"id":"crop-pass","type":"hook","site_symbol":"farm_tile_state",'
            '"trampoline_symbol":"crop_pass_trampoline"}'
        )
        self.map_path.write_text(
            f"0x{self.base + 16:08X} farm_tile_state\n"
            f"0x{self.base + 64:08X} mod_farm_tile_state\n"
            f"0x{self.base + 96:08X} crop_pass_trampoline\n"
            f"0x{self.base + 112:08X} __mips_trampoline_start_11_GF_FARM\n"
            f"0x{self.base + 80:08X} __mips_trampoline_end_11_GF_FARM\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(HookRegistrationError, "reversed bounds"):
            generate_hook_registry(
                self.overlay, map_path=self.map_path, image_path=self.image_path,
                base_address=self.base,
            )

    def test_rejects_trampoline_overlap_with_site(self):
        self._source(
            '{"id":"crop-pass","type":"hook","site_symbol":"farm_tile_state",'
            '"trampoline_symbol":"overlap_trampoline"}'
        )
        with self.assertRaises(HookRegistrationError):
            generate_hook_registry(
                self.overlay, map_path=self.map_path, image_path=self.image_path,
                base_address=self.base,
            )

    def test_declaration_flows_through_registry_plan_apply_and_validation(self):
        self._source(
            '{"id":"crop-pass","type":"hook","site_symbol":"farm_tile_state",'
            '"trampoline_symbol":"crop_pass_trampoline"}'
        )
        registry_path = self.overlay / "mod" / "hooks.json"
        first = write_hook_registry(
            self.overlay, registry_path, map_path=self.map_path,
            image_path=self.image_path, base_address=self.base,
        )
        first_bytes = registry_path.read_bytes()
        second = write_hook_registry(
            self.overlay, registry_path, map_path=self.map_path,
            image_path=self.image_path, base_address=self.base,
        )
        self.assertEqual(first, second)
        self.assertEqual(registry_path.read_bytes(), first_bytes)

        original = self.image_path.read_bytes()
        plan = build_integration_plan(
            original, base_address=self.base, overlay="11_GF_FARM",
            registry_path=registry_path, map_path=self.map_path,
        )
        self.assertEqual(len(plan.entries), 1)
        self.assertEqual(plan.entries[0]["id"], "crop-pass")
        patched = apply_integration_plan(
            original, plan, base_address=self.base, overlay="11_GF_FARM",
            registry_path=registry_path, map_path=self.map_path,
        )
        report = validate_integrated_image(original, patched, plan)
        self.assertEqual(report.image_size, len(original))
        self.assertTrue(report.changed_ranges)
        self.assertNotEqual(patched[16:24], original[16:24])
        self.assertNotEqual(patched[96:112], original[96:112])

    def test_writes_registry_only_after_successful_generation(self):
        self._source(
            '{"id":"crop-pass","type":"hook","site_symbol":"farm_tile_state",'
            '"trampoline_symbol":"crop_pass_trampoline"}'
        )
        output = self.overlay / "mod" / "hooks.json"
        existing = {
            "schema_version": 1,
            "module": "11_GF_FARM",
            "hooks": [{"id": "manual-jal", "type": "jal"}],
        }
        output.write_text(__import__("json").dumps(existing), encoding="utf-8")
        registry = write_hook_registry(
            self.overlay, output, map_path=self.map_path,
            image_path=self.image_path, base_address=self.base,
        )
        self.assertEqual(registry["hooks"][0], existing["hooks"][0])
        self.assertEqual(registry["hooks"][1]["id"], "crop-pass")
        self.assertEqual(output.read_text(encoding="utf-8"),
                         __import__("json").dumps(registry, indent=2) + "\n")


if __name__ == "__main__":
    unittest.main()

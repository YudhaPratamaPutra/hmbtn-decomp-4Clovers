import struct
import tempfile
import unittest
from pathlib import Path

from tools.mips.registration import (
    HookRegistrationError,
    generate_hook_registry,
    write_hook_registry,
)


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
            f"0x{self.base + 64:08X} mod_farm_tile_state\n",
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
            '"trampoline_offset":"0x60"}'
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

    def test_requires_explicit_trampoline_offset(self):
        self._source(
            '{"id":"crop-pass","type":"hook","site_symbol":"farm_tile_state"}'
        )
        with self.assertRaises(HookRegistrationError):
            generate_hook_registry(
                self.overlay, map_path=self.map_path, image_path=self.image_path,
                base_address=self.base,
            )

    def test_rejects_missing_target_symbol(self):
        self._source(
            '{"id":"crop-pass","type":"hook","site_symbol":"not_in_map",'
            '"trampoline_offset":96}'
        )
        with self.assertRaises(HookRegistrationError):
            generate_hook_registry(
                self.overlay, map_path=self.map_path, image_path=self.image_path,
                base_address=self.base,
            )

    def test_rejects_trampoline_overlap_with_site(self):
        self._source(
            '{"id":"crop-pass","type":"hook","site_symbol":"farm_tile_state",'
            '"trampoline_offset":16}'
        )
        with self.assertRaises(HookRegistrationError):
            generate_hook_registry(
                self.overlay, map_path=self.map_path, image_path=self.image_path,
                base_address=self.base,
            )

    def test_writes_registry_only_after_successful_generation(self):
        self._source(
            '{"id":"crop-pass","type":"hook","site_symbol":"farm_tile_state",'
            '"trampoline_offset":96}'
        )
        output = self.overlay / "mod" / "hooks.json"
        registry = write_hook_registry(
            self.overlay, output, map_path=self.map_path,
            image_path=self.image_path, base_address=self.base,
        )
        self.assertEqual(output.read_text(encoding="utf-8"), 
                         __import__("json").dumps(registry, indent=2) + "\n")


if __name__ == "__main__":
    unittest.main()

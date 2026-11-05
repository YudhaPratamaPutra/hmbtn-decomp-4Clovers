import json
import struct
import tempfile
import unittest
from pathlib import Path

from tools.mips.jal import _encode_jal
from tools.mips.jal_declarations import (
    JalDeclarationError, scan_jal_declarations, discover_jal_declarations,
)
from tools.mips.jal_registration import (
    JalRegistrationError, generate_jal_registry, write_jal_registry,
)


class JalDeclarationTests(unittest.TestCase):
    def test_scans_explicit_declaration(self):
        source = '/* MIPS_AUTO_JAL: {"id":"farm-call","type":"jal","site_symbol":"farm_callsite","target_symbol":"mod_target"} */'
        item = scan_jal_declarations(source, source_name="mod/calls.c")[0]
        self.assertEqual(item.site_symbol, "farm_callsite")
        self.assertEqual(item.target_symbol, "mod_target")
        self.assertEqual(item.to_dict()["type"], "jal")

    def test_ignores_marker_text_inside_string_and_unmarked_comment(self):
        source = r'''
const char *s = "/* MIPS_AUTO_JAL: {bad} */";
/* Example MIPS_AUTO_JAL: {"id":"fake","type":"jal","site_symbol":"x","target_symbol":"y"} */
'''
        self.assertEqual(scan_jal_declarations(source), [])

    def test_rejects_line_comment_and_invalid_metadata(self):
        with self.assertRaises(JalDeclarationError):
            scan_jal_declarations('// MIPS_AUTO_JAL: {}\n')
        with self.assertRaises(JalDeclarationError):
            scan_jal_declarations('/* MIPS_AUTO_JAL: {"id":"x","type":"jal","site_symbol":"x"} */')

    def test_rejects_duplicate_ids_and_sites(self):
        one = '/* MIPS_AUTO_JAL: {"id":"x","type":"jal","site_symbol":"site","target_symbol":"target"} */'
        with self.assertRaises(JalDeclarationError):
            scan_jal_declarations(one + one.replace('"site"', '"site2"'))
        with self.assertRaises(JalDeclarationError):
            scan_jal_declarations(one + one.replace('"id":"x"', '"id":"y"'))


class JalRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.overlay = self.root / "11_GF_FARM"
        (self.overlay / "mod").mkdir(parents=True)
        self.base = 0x80010000
        self.image = self.root / "overlay.bin"
        self.map = self.root / "program.map"
        self.site = self.base + 16
        self.target = self.base + 64
        data = bytearray(128)
        self.word = _encode_jal(self.site, self.target)
        struct.pack_into("<I", data, 16, self.word)
        self.image.write_bytes(data)
        self.map.write_text(
            f"0x{self.site:08X} farm_callsite\n"
            f"0x{self.target:08X} mod_target\n",
            encoding="utf-8",
        )
        (self.overlay / "mod" / "calls.c").write_text(
            '/* MIPS_AUTO_JAL: {"id":"farm-call","type":"jal",'
            '"site_symbol":"farm_callsite","target_symbol":"mod_target"} */\n',
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_generates_registry_from_linker_symbols_and_exact_jal_word(self):
        registry = generate_jal_registry(
            self.overlay, map_path=self.map, image_path=self.image,
            base_address=self.base,
        )
        entry = registry["jal"][0]
        self.assertEqual(entry["file_offset"], "0x10")
        self.assertEqual(entry["expected_word"], f"0x{self.word:08X}")
        self.assertEqual(entry["expected_target"], f"0x{self.target:08X}")
        self.assertEqual(entry["target_symbol"], "mod_target")

    def test_rejects_site_symbol_that_does_not_point_to_jal(self):
        data = bytearray(self.image.read_bytes())
        struct.pack_into("<I", data, 16, 0)
        self.image.write_bytes(data)
        with self.assertRaisesRegex(JalRegistrationError, "does not point to a JAL"):
            generate_jal_registry(
                self.overlay, map_path=self.map, image_path=self.image,
                base_address=self.base,
            )

    def test_rejects_encoded_target_mismatch(self):
        self.map.write_text(
            f"0x{self.site:08X} farm_callsite\n"
            f"0x{self.base + 80:08X} mod_target\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(JalRegistrationError, "does not match target symbol"):
            generate_jal_registry(
                self.overlay, map_path=self.map, image_path=self.image,
                base_address=self.base,
            )

    def test_writer_preserves_existing_hook_entries(self):
        output = self.overlay / "mod" / "hooks.json"
        output.write_text(json.dumps({
            "schema_version": 1, "module": "11_GF_FARM",
            "hooks": [{"id": "existing-hook", "type": "hook"}],
        }), encoding="utf-8")
        registry = write_jal_registry(
            self.overlay, output, map_path=self.map, image_path=self.image,
            base_address=self.base,
        )
        self.assertEqual([entry["type"] for entry in registry["hooks"]], ["hook", "jal"])
        self.assertEqual(json.loads(output.read_text())["hooks"], registry["hooks"])


if __name__ == "__main__":
    unittest.main()

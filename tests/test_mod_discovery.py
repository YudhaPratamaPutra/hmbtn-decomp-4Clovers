import json
import tempfile
import unittest
from pathlib import Path

from tools.mips.discovery import ModDiscoveryError, discover_mod_sources


class ModDiscoveryTests(unittest.TestCase):
    def make_overlay(self, root):
        overlay = root / "11_GF_TEST"
        (overlay / "mod" / "menu").mkdir(parents=True)
        (overlay / "mod" / "mod_main.c").write_text("void mod_main(void) {}\n")
        (overlay / "mod" / "mod_main.h").write_text("void mod_main(void);\n")
        (overlay / "mod" / "menu" / "inventory.c").write_text("void inventory(void) {}\n")
        (overlay / "mod" / "menu" / "inventory.h").write_text("void inventory(void);\n")
        (overlay / "mod" / "hooks.json").write_text(json.dumps({
            "schema_version": 1, "module": "11_GF_TEST", "hooks": []
        }))
        return overlay

    def test_recursive_sorted_inventory(self):
        with tempfile.TemporaryDirectory() as temp:
            overlay = self.make_overlay(Path(temp))
            result = discover_mod_sources(overlay)
            self.assertEqual(result.sources, (
                "mod/menu/inventory.c", "mod/mod_main.c",
            ))
            self.assertEqual(result.headers, (
                "mod/menu/inventory.h", "mod/mod_main.h",
            ))
            self.assertEqual(result.registry_hooks, 0)

    def test_reject_registry_wrong_module(self):
        with tempfile.TemporaryDirectory() as temp:
            overlay = self.make_overlay(Path(temp))
            (overlay / "mod" / "hooks.json").write_text(json.dumps({
                "schema_version": 1, "module": "OTHER", "hooks": []
            }))
            with self.assertRaises(ModDiscoveryError):
                discover_mod_sources(overlay)

    def test_reject_registry_wrong_schema(self):
        with tempfile.TemporaryDirectory() as temp:
            overlay = self.make_overlay(Path(temp))
            (overlay / "mod" / "hooks.json").write_text(json.dumps({
                "schema_version": 2, "module": "11_GF_TEST", "hooks": []
            }))
            with self.assertRaises(ModDiscoveryError):
                discover_mod_sources(overlay)

    def test_reject_registry_non_array_hooks(self):
        with tempfile.TemporaryDirectory() as temp:
            overlay = self.make_overlay(Path(temp))
            (overlay / "mod" / "hooks.json").write_text(json.dumps({
                "schema_version": 1, "module": "11_GF_TEST", "hooks": {}
            }))
            with self.assertRaises(ModDiscoveryError):
                discover_mod_sources(overlay)

    def test_missing_mod_directory_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            overlay = Path(temp) / "11_GF_TEST"
            overlay.mkdir()
            with self.assertRaises(ModDiscoveryError):
                discover_mod_sources(overlay)


if __name__ == "__main__":
    unittest.main()

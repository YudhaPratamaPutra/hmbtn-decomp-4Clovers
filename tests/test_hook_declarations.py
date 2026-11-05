import tempfile
import unittest
from pathlib import Path

from tools.mips.declarations import (
    HookDeclarationError,
    discover_hook_declarations,
    scan_hook_declarations,
)


class HookDeclarationScannerTests(unittest.TestCase):
    def test_scans_explicit_function_definition(self):
        source = '''#include "game.h"
/* MIPS_AUTO_HOOK: {"id":"crop-pass","type":"hook","site_symbol":"farm_tile_state"} */
s32 mod_farm_tile_state(s16 column, s16 row, s32 mode)
{
    return 0;
}
'''
        result = scan_hook_declarations(source, source_name="mod/crop.c")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].hook_symbol, "mod_farm_tile_state")
        self.assertEqual(result[0].site_symbol, "farm_tile_state")
        self.assertEqual(result[0].to_dict()["type"], "hook")

    def test_ignores_marker_text_inside_string_and_unmarked_comment(self):
        source = r'''
const char *text = "/* MIPS_AUTO_HOOK: {bad json} */";
/* Example only: MIPS_AUTO_HOOK: {"id":"fake","type":"hook","site_symbol":"fake"} */
void ordinary_mod(void) { }
'''
        self.assertEqual(scan_hook_declarations(source), [])

    def test_rejects_line_comment_marker(self):
        source = '// MIPS_AUTO_HOOK: {"id":"x","type":"hook","site_symbol":"target"}\n'
        with self.assertRaises(HookDeclarationError):
            scan_hook_declarations(source)

    def test_rejects_invalid_json(self):
        source = '/* MIPS_AUTO_HOOK: {broken} */\nvoid mod(void) { }\n'
        with self.assertRaises(HookDeclarationError):
            scan_hook_declarations(source)

    def test_rejects_missing_and_unknown_metadata_fields(self):
        for metadata in (
            '{"id":"x","type":"hook"}',
            '{"id":"x","type":"hook","site_symbol":"target","offset":12}',
        ):
            with self.subTest(metadata=metadata):
                with self.assertRaises(HookDeclarationError):
                    scan_hook_declarations(f"/* MIPS_AUTO_HOOK: {metadata} */\nvoid mod(void) {{ }}")

    def test_rejects_prototype_without_definition(self):
        source = '/* MIPS_AUTO_HOOK: {"id":"x","type":"hook","site_symbol":"target"} */\nvoid mod(void);\n'
        with self.assertRaises(HookDeclarationError):
            scan_hook_declarations(source)

    def test_rejects_duplicate_ids_and_targets(self):
        one = '/* MIPS_AUTO_HOOK: {"id":"x","type":"hook","site_symbol":"target"} */\nvoid first(void) { }\n'
        duplicate_id = one + '/* MIPS_AUTO_HOOK: {"id":"x","type":"hook","site_symbol":"other"} */\nvoid second(void) { }\n'
        with self.assertRaises(HookDeclarationError):
            scan_hook_declarations(duplicate_id)
        duplicate_target = one + '/* MIPS_AUTO_HOOK: {"id":"y","type":"hook","site_symbol":"target"} */\nvoid second(void) { }\n'
        with self.assertRaises(HookDeclarationError):
            scan_hook_declarations(duplicate_target)

    def test_rejects_non_identifier_target(self):
        source = '/* MIPS_AUTO_HOOK: {"id":"x","type":"hook","site_symbol":"target+4"} */\nvoid mod(void) { }\n'
        with self.assertRaises(HookDeclarationError):
            scan_hook_declarations(source)

    def test_discovers_nested_sources_in_sorted_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            overlay = Path(tmp) / "11_GF_FARM"
            (overlay / "mod" / "nested").mkdir(parents=True)
            declaration = '/* MIPS_AUTO_HOOK: {"id":"x","type":"hook","site_symbol":"target"} */\nvoid mod(void) { }\n'
            (overlay / "mod" / "z.c").write_text(declaration, encoding="utf-8")
            (overlay / "mod" / "nested" / "a.c").write_text(
                '/* MIPS_AUTO_HOOK: {"id":"y","type":"hook","site_symbol":"target2"} */\nvoid mod2(void) { }\n',
                encoding="utf-8",
            )
            result = discover_hook_declarations(overlay)
            self.assertEqual([item.source for item in result], [
                "mod/nested/a.c", "mod/z.c"
            ])


if __name__ == "__main__":
    unittest.main()

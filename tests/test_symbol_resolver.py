import tempfile
import unittest
from pathlib import Path

from tools.mips.symbols import (
    SymbolResolverError, load_linker_map, parse_linker_map,
    resolve_symbol, resolve_symbols,
)


MAP = """                0x80010000                _start
 .text          0x80010000       0x100 build/start.o
                0x80010120                farm_enter_dispatch
                0x80010120                farm_enter_dispatch
                0x80010200                item_merge_dispatch = .
 .data          0x80020000        0x20 build/data.o
                0x80020004                global_counter
"""


class SymbolResolverTests(unittest.TestCase):
    def test_parse_symbol_rows_and_ignore_sections(self):
        symbols = parse_linker_map(MAP)
        self.assertIn("farm_enter_dispatch", symbols)
        self.assertNotIn(".text", symbols)
        self.assertNotIn(".data", symbols)

    def test_resolve_exact_symbol(self):
        result = resolve_symbol(parse_linker_map(MAP), "farm_enter_dispatch")
        self.assertEqual(result.address, 0x80010120)
        self.assertEqual(result.definition_lines, (3, 4))

    def test_resolve_assignment_style_symbol(self):
        result = resolve_symbol(parse_linker_map(MAP), "item_merge_dispatch")
        self.assertEqual(result.address, 0x80010200)

    def test_duplicate_symbol_same_address_is_consistent(self):
        result = resolve_symbol(parse_linker_map(MAP), "farm_enter_dispatch")
        self.assertEqual(result.address, 0x80010120)

    def test_ambiguous_symbol_is_rejected(self):
        symbols = parse_linker_map(
            "0x80010000 duplicate_name\n0x80020000 duplicate_name\n"
        )
        with self.assertRaises(SymbolResolverError):
            resolve_symbol(symbols, "duplicate_name")

    def test_missing_symbol_is_rejected(self):
        with self.assertRaises(SymbolResolverError):
            resolve_symbol(parse_linker_map(MAP), "not_in_map")

    def test_batch_resolution_preserves_order(self):
        result = resolve_symbols(
            parse_linker_map(MAP), ["farm_enter_dispatch", "item_merge_dispatch"]
        )
        self.assertEqual([item.name for item in result],
                         ["farm_enter_dispatch", "item_merge_dispatch"])

    def test_batch_fails_when_one_symbol_missing(self):
        with self.assertRaises(SymbolResolverError):
            resolve_symbols(parse_linker_map(MAP), ["_start", "missing"])

    def test_duplicate_requested_names_rejected(self):
        with self.assertRaises(SymbolResolverError):
            resolve_symbols(parse_linker_map(MAP), ["_start", "_start"])

    def test_load_map_from_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "program.map"
            path.write_text(MAP, encoding="utf-8")
            symbols = load_linker_map(path)
            self.assertEqual(resolve_symbol(symbols, "_start").address, 0x80010000)


if __name__ == "__main__":
    unittest.main()

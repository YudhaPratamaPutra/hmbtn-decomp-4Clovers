import unittest
from pathlib import Path


class FarmHookSiteExportTests(unittest.TestCase):
    def test_farm_tile_state_is_declared_with_external_linkage(self):
        source = Path("src/overlay/11_GF_FARM/farm_probe.c").read_text(
            encoding="utf-8"
        )
        declaration = "s32 farm_tile_state(s16 column, s16 row, s32 mode);"
        definition = "s32 farm_tile_state(s16 column, s16 row, s32 mode) {"

        self.assertIn(declaration, source)
        self.assertIn(definition, source)
        self.assertNotIn("static " + declaration, source)
        self.assertNotIn("static " + definition, source)


    def test_mod_tile_query_guards_non_item_values_and_missing_rules(self):
        source = Path("src/overlay/11_GF_FARM/mod/no_plant_collision.c").read_text(
            encoding="utf-8"
        )
        item_guard = "if (record->value >= ITEM_COUNT) {\n        return 0;\n    }"
        rule_guard = "if (ruleIndex < 0) {\n        return 2;\n    }"

        self.assertIn(item_guard, source)
        self.assertIn(rule_guard, source)
        self.assertLess(source.index(item_guard), source.index("entry[record->value].crop"))
        self.assertLess(source.index(rule_guard), source.index("game_state.tileRules[ruleIndex].status"))


if __name__ == "__main__":
    unittest.main()

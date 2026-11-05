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


if __name__ == "__main__":
    unittest.main()

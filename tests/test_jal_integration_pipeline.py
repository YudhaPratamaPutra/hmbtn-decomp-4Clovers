"""End-to-end tests for source-declared JAL integration."""
import json
import struct
import tempfile
import unittest
from pathlib import Path

from tools.mips.jal import _encode_jal
from tools.mips.jal_registration import write_jal_registry
from tools.mips.integration import build_integration_plan, apply_integration_plan
from tools.mips.validation import validate_integrated_image


class JalIntegrationPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.overlay = self.root / "11_GF_FARM"
        (self.overlay / "mod").mkdir(parents=True)
        self.base = 0x80010000
        self.site = self.base + 0x10
        self.target = self.base + 0x40
        self.image_path = self.root / "11_GF_FARM.bin"
        self.map_path = self.root / "program.map"
        self.registry_path = self.overlay / "mod" / "hooks.json"

        image = bytearray(0x80)
        self.original_word = _encode_jal(self.site, self.target)
        struct.pack_into("<I", image, 0x10, self.original_word)
        self.original_image = bytes(image)
        self.image_path.write_bytes(self.original_image)
        self.map_path.write_text(
            f"0x{self.site:08X} farm_callsite\\n"
            f"0x{self.target:08X} mod_target\\n",
            encoding="utf-8",
        )
        (self.overlay / "mod" / "calls.c").write_text(
            '/* MIPS_AUTO_JAL: {"id":"farm-call","type":"jal",'
            '"site_symbol":"farm_callsite","target_symbol":"mod_target"} */\\n',
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_source_declaration_flows_through_registry_plan_apply_and_validation(self):
        registry = write_jal_registry(
            self.overlay,
            self.registry_path,
            map_path=self.map_path,
            image_path=self.image_path,
            base_address=self.base,
        )
        self.assertEqual(len(registry["hooks"]), 1)
        self.assertEqual(registry["hooks"][0]["type"], "jal")

        plan = build_integration_plan(
            self.original_image,
            base_address=self.base,
            overlay="11_GF_FARM",
            registry_path=self.registry_path,
            map_path=self.map_path,
        )
        self.assertEqual(len(plan.entries), 1)
        self.assertEqual(plan.entries[0]["id"], "farm-call")
        self.assertEqual(plan.entries[0]["type"], "jal")

        output = apply_integration_plan(
            self.original_image,
            plan,
            base_address=self.base,
            overlay="11_GF_FARM",
            registry_path=self.registry_path,
            map_path=self.map_path,
        )
        report = validate_integrated_image(self.original_image, output, plan)

        self.assertEqual(len(output), len(self.original_image))
        self.assertEqual(struct.unpack_from("<I", output, 0x10)[0], self.original_word)
        self.assertEqual(report.image_size, len(self.original_image))
        self.assertEqual(report.authorized_ranges, ((0x10, 0x14, "farm-call"),))
        self.assertEqual(report.changed_ranges, ())

    def test_registry_refresh_is_idempotent(self):
        first = write_jal_registry(
            self.overlay,
            self.registry_path,
            map_path=self.map_path,
            image_path=self.image_path,
            base_address=self.base,
        )
        second = write_jal_registry(
            self.overlay,
            self.registry_path,
            map_path=self.map_path,
            image_path=self.image_path,
            base_address=self.base,
        )
        self.assertEqual(first, second)
        self.assertEqual(json.loads(self.registry_path.read_text())["hooks"], second["hooks"])


if __name__ == "__main__":
    unittest.main()

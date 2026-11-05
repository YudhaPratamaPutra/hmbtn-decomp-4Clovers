import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.maspsx.maspsx import MaspsxProcessor


class TrampolineSectionTests(unittest.TestCase):
    def test_overlay_linker_template_keeps_and_brackets_trampoline_inputs(self):
        template = Path("cmake/overlay.ld.in").read_text(encoding="utf-8")
        data = template.index("@DATA@")
        start = template.index("__mips_trampoline_start_@NAME@")
        keep = template.index("KEEP(*(.mips_trampoline.@NAME@))")
        end = template.index("__mips_trampoline_end_@NAME@")
        bss = template.index("@BSS@")

        self.assertLess(data, start)
        self.assertLess(start, keep)
        self.assertLess(keep, end)
        self.assertLess(end, bss)

    def test_trampoline_macro_reserves_four_words_in_named_section(self):
        header = Path("src/overlay/11_GF_FARM/mod/mips_auto_hook.h").read_text(
            encoding="utf-8"
        )
        self.assertIn('section(".mips_trampoline.11_GF_FARM")', header)
        self.assertIn("aligned(4)", header)
        self.assertIn("unsigned int symbol[4]", header)
        self.assertIn("{0, 0, 0, 0}", header)

    def test_linker_keeps_each_overlay_trampoline_in_its_own_output_section(self):
        assembler = shutil.which("as")
        linker = shutil.which("ld")
        nm = shutil.which("nm")
        if not all((assembler, linker, nm)):
            self.skipTest("GNU as, ld, and nm are required for linker-section fixture")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            farm_source = root / "farm.s"
            other_source = root / "other.s"
            farm_object = root / "farm.o"
            other_object = root / "other.o"
            script = root / "fixture.ld"
            elf = root / "fixture.elf"
            farm_source.write_text(
                '.section .mips_trampoline.11_GF_FARM,"aw",@progbits\n'
                '.globl farm_trampoline\nfarm_trampoline:\n'
                '.zero 16\n',
                encoding="utf-8",
            )
            other_source.write_text(
                '.section .mips_trampoline.12_OTHER,"aw",@progbits\n'
                '.globl other_trampoline\nother_trampoline:\n'
                '.zero 16\n',
                encoding="utf-8",
            )
            template = Path("cmake/overlay.ld.in").read_text(encoding="utf-8")

            def overlay_block(name, object_name):
                values = {
                    "@NAME@": name,
                    "@REGION@": "low",
                    "@LIST_FILE@": "fixture",
                    "@HEADER@": object_name,
                    "@RODATA@": "",
                    "@TEXT@": "",
                    "@DATA@": "",
                    "@BSS@": "",
                }
                block = template
                for token, value in values.items():
                    block = block.replace(token, value)
                return block

            script.write_text(
                "overlay_low = 0x80010000;\n"
                + overlay_block("11_GF_FARM", "farm.o")
                + overlay_block("12_OTHER", "other.o"),
                encoding="utf-8",
            )
            subprocess.run([assembler, str(farm_source), "-o", str(farm_object)],
                           check=True, capture_output=True, text=True)
            subprocess.run([assembler, str(other_source), "-o", str(other_object)],
                           check=True, capture_output=True, text=True)
            link_result = subprocess.run(
                [linker, "-T", str(script), "-Map", str(root / "fixture.map"),
                 "-o", str(elf), str(farm_object), str(other_object)],
                check=False, capture_output=True, text=True, cwd=root,
            )
            self.assertEqual(link_result.returncode, 0, link_result.stderr)
            symbols = subprocess.run([nm, "-n", str(elf)], check=True,
                                     capture_output=True, text=True).stdout
            self.assertIn("__mips_trampoline_start_11_GF_FARM", symbols)
            self.assertIn("__mips_trampoline_end_11_GF_FARM", symbols)
            self.assertIn("__mips_trampoline_start_12_OTHER", symbols)
            self.assertIn("__mips_trampoline_end_12_OTHER", symbols)
            symbol_addresses = {}
            for line in symbols.splitlines():
                fields = line.split()
                if len(fields) == 3:
                    symbol_addresses[fields[2]] = int(fields[0], 16)
            farm_start = symbol_addresses["__mips_trampoline_start_11_GF_FARM"]
            farm_end = symbol_addresses["__mips_trampoline_end_11_GF_FARM"]
            other_start = symbol_addresses["__mips_trampoline_start_12_OTHER"]
            other_end = symbol_addresses["__mips_trampoline_end_12_OTHER"]
            self.assertEqual(farm_end - farm_start, 16)
            self.assertEqual(other_end - other_start, 16)
            self.assertTrue(farm_start <= symbol_addresses["farm_trampoline"] < farm_end)
            self.assertTrue(other_start <= symbol_addresses["other_trampoline"] < other_end)

    def test_maspsx_preserves_trampoline_section_and_storage_directives(self):
        source = [
            '.section .mips_trampoline.11_GF_FARM',
            '.align 2',
            '.globl crop_pass_trampoline',
            'crop_pass_trampoline:',
            '.word 0',
            '.word 0',
            '.word 0',
            '.word 0',
        ]

        output = MaspsxProcessor(source).process_lines()

        self.assertIn('.section .mips_trampoline.11_GF_FARM', output)
        self.assertIn('.align 2', output)
        self.assertIn('.globl crop_pass_trampoline', output)
        self.assertIn('crop_pass_trampoline:', output)
        self.assertEqual(output.count('.word 0'), 4)


if __name__ == "__main__":
    unittest.main()

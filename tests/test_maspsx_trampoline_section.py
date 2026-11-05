import unittest
from pathlib import Path

from tools.maspsx.maspsx import MaspsxProcessor


class TrampolineSectionTests(unittest.TestCase):
    def test_overlay_linker_template_keeps_and_brackets_trampoline_inputs(self):
        template = Path("cmake/overlay.ld.in").read_text(encoding="utf-8")
        data = template.index("@DATA@")
        start = template.index("__mips_trampoline_start")
        keep = template.index("KEEP(*(.mips_trampoline))")
        end = template.index("__mips_trampoline_end")
        bss = template.index("@BSS@")

        self.assertLess(data, start)
        self.assertLess(start, keep)
        self.assertLess(keep, end)
        self.assertLess(end, bss)

    def test_trampoline_macro_reserves_four_words_in_named_section(self):
        header = Path("src/overlay/11_GF_FARM/mod/mips_auto_hook.h").read_text(
            encoding="utf-8"
        )
        self.assertIn('section(".mips_trampoline")', header)
        self.assertIn("aligned(4)", header)
        self.assertIn("unsigned int symbol[4]", header)
        self.assertIn("{0, 0, 0, 0}", header)

    def test_maspsx_preserves_trampoline_section_and_storage_directives(self):
        source = [
            '.section .mips_trampoline',
            '.align 2',
            '.globl crop_pass_trampoline',
            'crop_pass_trampoline:',
            '.word 0',
            '.word 0',
            '.word 0',
            '.word 0',
        ]

        output = MaspsxProcessor(source).process_lines()

        self.assertIn('.section .mips_trampoline', output)
        self.assertIn('.align 2', output)
        self.assertIn('.globl crop_pass_trampoline', output)
        self.assertIn('crop_pass_trampoline:', output)
        self.assertEqual(output.count('.word 0'), 4)


if __name__ == "__main__":
    unittest.main()

import unittest

from tools.maspsx.maspsx import MaspsxProcessor


class TrampolineSectionTests(unittest.TestCase):
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

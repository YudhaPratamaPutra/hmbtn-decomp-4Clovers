import struct
import unittest

from tools.mips.analysis import MipsAnalysisError, analyze_mips_image
from tools.mips.core import encode_branch, encode_j


class MipsAnalysisTests(unittest.TestCase):
    def test_scans_instructions_and_collects_direct_references(self):
        base = 0x80010000
        words = (
            encode_branch(4, base, base + 0x10, 8, 0),
            encode_j(3, base + 4, base + 0x40),
            0x27BDFFE8,
        )
        image = struct.pack("<3I", *words)
        report = analyze_mips_image(image, base)
        self.assertEqual(report.decoded_count, 3)
        self.assertEqual(report.undecoded_count, 0)
        self.assertEqual(
            [(item["kind"], item["target"]) for item in report.references],
            [("branch", "0x80010010"), ("jal", "0x80010040")],
        )
        self.assertEqual(report.instructions[2]["mnemonic"], "addiu")

    def test_keeps_undecodable_words_as_scan_results(self):
        image = struct.pack("<2I", 0xFFFFFFFF, 0x27BDFFE8)
        report = analyze_mips_image(image, 0x80010000)
        self.assertEqual(report.decoded_count, 1)
        self.assertEqual(report.undecoded_count, 1)
        self.assertFalse(report.instructions[0]["decoded"])
        self.assertEqual(report.instructions[1]["mnemonic"], "addiu")

    def test_explicit_range_is_respected(self):
        image = struct.pack("<3I", 0x27BDFFE8, 0x27BDFFE8, 0x27BDFFE8)
        report = analyze_mips_image(
            image, 0x80010000, start_offset=4, end_offset=8
        )
        self.assertEqual(report.start_offset, 4)
        self.assertEqual(report.end_offset, 8)
        self.assertEqual(len(report.instructions), 1)
        self.assertEqual(report.instructions[0]["file_offset"], "0x4")

    def test_rejects_unaligned_or_out_of_image_ranges(self):
        image = b"\0" * 8
        with self.assertRaises(MipsAnalysisError):
            analyze_mips_image(image, 0x80010000, start_offset=2)
        with self.assertRaises(MipsAnalysisError):
            analyze_mips_image(image, 0x80010000, end_offset=12)


if __name__ == "__main__":
    unittest.main()

import struct
import tempfile
import unittest
from pathlib import Path

from tools.afile import Member, SECTOR, pack


class AFileIntegratedPackingTests(unittest.TestCase):
    def test_pack_uses_integrated_sidecar_only_for_listed_members(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = root / "original"
            built = root / "built"
            integrated = root / "integrated"
            for directory in (original, built, integrated):
                directory.mkdir()

            (original / "keep.bin").write_bytes(b"ORIGINAL")
            (built / "farm.bin").write_bytes(b"BUILT-FARM")
            (built / "other.bin").write_bytes(b"BUILT-OTHER")
            (integrated / "farm.bin").write_bytes(b"PATCHED-FARM")

            members = [
                Member(0, "keep.bin", "original", "keep.bin"),
                Member(1, "farm.bin", "built", "farm.bin"),
                Member(2, "other.bin", "built", "other.bin"),
            ]
            output_bin = root / "A_FILE.BIN"
            output_hdt = root / "A_FILE.HDT"

            pack(
                members, original, built, output_bin, output_hdt,
                integrated=integrated,
                integrated_members={"farm.bin"},
            )

            archive = output_bin.read_bytes()
            offsets = struct.unpack("<4I", output_hdt.read_bytes())
            self.assertEqual(offsets, (0, SECTOR, 2 * SECTOR, 3 * SECTOR))
            self.assertEqual(archive[offsets[0]:offsets[1]].rstrip(b"\\0"), b"ORIGINAL")
            self.assertEqual(archive[offsets[1]:offsets[2]].rstrip(b"\\0"), b"PATCHED-FARM")
            self.assertEqual(archive[offsets[2]:offsets[3]].rstrip(b"\\0"), b"BUILT-OTHER")

    def test_listed_integrated_member_must_exist(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = root / "original"
            built = root / "built"
            integrated = root / "integrated"
            for directory in (original, built, integrated):
                directory.mkdir()
            (built / "farm.bin").write_bytes(b"BUILT")
            with self.assertRaises(FileNotFoundError):
                pack(
                    [Member(0, "farm.bin", "built", "farm.bin")],
                    original, built, root / "A_FILE.BIN", root / "A_FILE.HDT",
                    integrated=integrated,
                    integrated_members={"farm.bin"},
                )


if __name__ == "__main__":
    unittest.main()

import subprocess
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class OverlayModCMakeTests(unittest.TestCase):
    def test_each_overlay_compiles_only_its_mod_sources_and_uses_its_headers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "src/overlay/alpha/mod/nested").mkdir(parents=True)
            (root / "src/overlay/beta/mod").mkdir(parents=True)

            (root / "src/overlay/alpha/header.c").write_text("void alpha_header(void) {}\n")
            (root / "src/overlay/alpha/game.c").write_text("void alpha_game(void) {}\n")
            (root / "src/overlay/alpha/mod/alpha_mod.c").write_text(
                '#include "alpha_mod.h"\nvoid alpha_mod(void) {}\n'
            )
            (root / "src/overlay/alpha/mod/alpha_mod.h").write_text(
                "void alpha_mod(void);\n"
            )
            (root / "src/overlay/alpha/mod/nested/alpha_nested.h").write_text(
                "void alpha_nested(void);\n"
            )

            (root / "src/overlay/beta/header.c").write_text("void beta_header(void) {}\n")
            (root / "src/overlay/beta/game.c").write_text("void beta_game(void) {}\n")
            (root / "src/overlay/beta/mod/beta_mod.c").write_text(
                '#include "beta_mod.h"\nvoid beta_mod(void) {}\n'
            )
            (root / "src/overlay/beta/mod/beta_mod.h").write_text(
                "void beta_mod(void);\n"
            )

            (root / "src/overlay/alpha/CMakeLists.txt").write_text(
                "psx_overlay(alpha FILE alpha.bin REGION low SOURCES header.c game.c)\n"
            )
            (root / "src/overlay/beta/CMakeLists.txt").write_text(
                "psx_overlay(beta FILE beta.bin REGION low SOURCES header.c game.c)\n"
            )

            cmake_lists = f'''cmake_minimum_required(VERSION 3.20)
project(overlay_mod_test NONE)
find_package(Python3 3.10 REQUIRED COMPONENTS Interpreter)
set(PSX_CPP /usr/bin/cpp)
set(PSX_CPP_FLAGS -I${{CMAKE_SOURCE_DIR}}/include)
set(PSX_CC1 /bin/true)
set(PSX_CC1_FLAGS -O2)
set(PSX_MASPSX_FLAGS)
set(PSX_AS /bin/true)
set(PSX_AS_FLAGS)
set(PSX_OBJCOPY /bin/true)
set(PSX_COMPILE_TOOLS)
include("{(REPOSITORY_ROOT / "cmake/psx.cmake").as_posix()}")
psx_overlay_region(low 0x800B7E20)
add_subdirectory(src/overlay/alpha)
add_subdirectory(src/overlay/beta)
'''
            (root / "CMakeLists.txt").write_text(cmake_lists)

            build = root / "build"
            subprocess.run(
                ["cmake", "-S", str(root), "-B", str(build)],
                check=True,
                capture_output=True,
                text=True,
            )

            alpha_makefiles = list(
                (build / "src/overlay/alpha/CMakeFiles/alpha_objects.dir").glob("build.make")
            )
            beta_makefiles = list(
                (build / "src/overlay/beta/CMakeFiles/beta_objects.dir").glob("build.make")
            )
            self.assertEqual(len(alpha_makefiles), 1)
            self.assertEqual(len(beta_makefiles), 1)

            alpha_commands = alpha_makefiles[0].read_text(encoding="utf-8")
            beta_commands = beta_makefiles[0].read_text(encoding="utf-8")

            self.assertIn("mod/alpha_mod.c", alpha_commands)
            self.assertIn(f"-I{root}/src/overlay/alpha/mod", alpha_commands)
            self.assertIn(f"-I{root}/src/overlay/alpha/mod/nested", alpha_commands)
            self.assertNotIn("beta_mod.c", alpha_commands)

            self.assertIn("mod/beta_mod.c", beta_commands)
            self.assertIn(f"-I{root}/src/overlay/beta/mod", beta_commands)
            self.assertNotIn("alpha_mod.c", beta_commands)
            self.assertNotIn("alpha/mod", beta_commands)


    def test_mips_pipeline_targets_are_created_per_overlay_with_mod_directories(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for overlay in ("alpha", "beta", "plain"):
                directory = root / "src/overlay" / overlay
                directory.mkdir(parents=True)
                (directory / "header.c").write_text("void overlay_header(void) {}\n")
                if overlay != "plain":
                    (directory / "mod").mkdir()

                (directory / "CMakeLists.txt").write_text(
                    f"psx_overlay({overlay} FILE {overlay}.bin REGION low SOURCES header.c)\n"
                )

            cmake_lists = f'''cmake_minimum_required(VERSION 3.20)
project(overlay_pipeline_test NONE)
find_package(Python3 3.10 REQUIRED COMPONENTS Interpreter)
set(PSX_CPP /usr/bin/cpp)
set(PSX_CPP_FLAGS)
set(PSX_CC1 /bin/true)
set(PSX_CC1_FLAGS)
set(PSX_MASPSX_FLAGS)
set(PSX_AS /bin/true)
set(PSX_AS_FLAGS)
set(PSX_OBJCOPY /bin/true)
set(PSX_COMPILE_TOOLS)
include("{(REPOSITORY_ROOT / "cmake/psx.cmake").as_posix()}")
psx_overlay_region(low 0x800B7E20)
add_subdirectory(src/overlay/alpha)
add_subdirectory(src/overlay/beta)
add_subdirectory(src/overlay/plain)
add_custom_target(program)
add_custom_target(afile)
psx_overlay_mips_integration_targets()
'''
            (root / "CMakeLists.txt").write_text(cmake_lists)
            build = root / "build"
            subprocess.run(
                ["cmake", "-S", str(root), "-B", str(build)],
                check=True,
                capture_output=True,
                text=True,
            )

            for overlay in ("alpha", "beta"):
                makefile = build / f"CMakeFiles/mips-integrate-{overlay}.dir/build.make"
                self.assertTrue(makefile.is_file())
                commands = makefile.read_text(encoding="utf-8")
                self.assertIn(f"{overlay}.bin", commands)
                self.assertIn(f"{overlay}.mod.bin", commands)
                self.assertIn("program.map", commands)
                self.assertIn("integrate-validate", commands)
                self.assertIn("integrated_A_FILE", commands)
                self.assertIn(`${overlay}.bin`, commands)

            manifest = build / "integrated_a_file_members.txt"
            self.assertEqual(manifest.read_text().splitlines(), ["alpha.bin", "beta.bin"])

            plain_makefile = build / "CMakeFiles/mips-integrate-plain.dir/build.make"
            self.assertFalse(plain_makefile.exists())
 
            dry_run = subprocess.run(
                ["cmake", "--build", str(build), "--target", "afile", "--", "-n"],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("mips-integrate-alpha", dry_run.stdout)
            self.assertIn("mips-integrate-beta", dry_run.stdout)


if __name__ == "__main__":
    unittest.main()

# MIPS / JAL / HOOK Auto Integrator — Backup

This is a standalone source backup of the Auto Integrator subsystem captured from commit ac597d0128e5e542b757827caea561c4e4c1b927 on branch feature/mips-log-quiet-output.

## Contents
- tools/mips_auto_integrator.py: command-line entry point, including the latest compact analysis output option (--summary).
- tools/mips/: MIPS analysis, discovery, symbol resolution, declarations, JAL and HOOK engines, registration, and integration pipeline.
- cmake/psx.cmake: build-system integration, including compact MIPS analysis invocation.
- tests/: focused tests for MIPS, JAL, HOOK, discovery, registration, and integration behavior.
- tools/MIPS_AUTO_INTEGRATOR.md: subsystem documentation.

## Important
This archive is a source backup, not an installer. It preserves the relevant subsystem files and their repository paths. It does not include the full HMBTN repository, game assets, toolchain binaries, or unrelated project files. When reusing it in a fresh Coalslav clone, review the CMake integration against that clone's current cmake/psx.cmake before replacing or merging it.

## Backup provenance
- Repository: YudhaPratamaPutra/hmbtn-decomp-4Clovers
- Source branch: feature/mips-log-quiet-output
- Source commit: ac597d0128e5e542b757827caea561c4e4c1b927
- Latest log fix: mips-analyze --summary, wired through cmake/psx.cmake

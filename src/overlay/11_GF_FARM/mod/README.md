# FARM mod sources

Place optional C source files anywhere under this directory. CMake recursively
discovers `*.c` files during configuration, including nested folders, and
appends them after the original FARM source list. Paths are sorted
deterministically and object paths retain their relative directory structure.

Example layout:

```text
mod/
├── mod_main.c
├── mod_main.h
├── mod_rucksack.c
├── mod_rucksack.h
├── menu/
│   ├── item_storage.c
│   └── item_storage.h
└── hooks.json
```

Headers are available through the FARM mod include path. Nested headers can be
included with their path relative to `mod/`, for example
`#include "menu/item_storage.h"`.

## Discovery inventory

Run:

```sh
python3 tools/mips_auto_integrator.py mod-discover \
  --overlay src/overlay/11_GF_FARM --json
```

The inventory reports source files, headers, and the hook registry entry count.
It validates the registry's schema version, overlay name, and hooks array.
It does not apply hooks or patch binaries.

## Automatic hook declaration and registration (V9.2)

Declare a hook directly above the mod function definition with a block comment:

```c
/* MIPS_AUTO_HOOK: {"id":"crop-pass","type":"hook","site_symbol":"farm_tile_state","trampoline_offset":"0x12340"} */
s32 mod_farm_tile_state(s16 column, s16 row, s32 mode)
{
    /* mod implementation */
}
```

The scanner reads these explicit fields:
- `id`: unique declaration identifier within the overlay.
- `type`: currently must be `hook`.
- `site_symbol`: exact original-game function symbol in the linker map.
- `trampoline_offset`: explicit file offset in the supplied overlay image. It must be independently verified as suitable storage; the generator never searches for or assumes free space.
- The immediately following C function definition supplies `hook_symbol`.

Run the scanner:

```sh
python3 tools/mips_auto_integrator.py hook-discover \\
  --overlay src/overlay/11_GF_FARM --json
```

V9.2 resolves both symbols against the exact linker map and derives the
hook-site file offset from the supplied image base. It reads the two displaced
instructions and the 16-byte trampoline guard from the supplied overlay image,
then validates the hook using the existing MIPS hook planner. It writes the
complete schema-v1 registry only after every declaration validates.

Run automatic registration after the overlay image and matching linker map
exist:

```sh
python3 tools/mips_auto_integrator.py hook-register \\
  --overlay src/overlay/11_GF_FARM \\
  --map build/program.map \\
  --input build/11_GF_FARM.bin \\
  --base 0x800B7E20
```

The command writes `mod/hooks.json` by default. It fails closed for missing or
ambiguous symbols, invalid instruction pairs, out-of-image offsets, and
overlapping patch regions. `trampoline_offset` remains a deliberate, explicit
choice: the generator checks the bytes found there but cannot prove that the
region is unused or safe. It does not modify the game image.

## Hook registry

For function-entry hooks, treat `hooks.json` as generated output rather than
hand-maintained input. Update the C declaration and rerun `hook-register`
whenever the linked image or linker map changes. JAL registrations remain
explicit until a corresponding source-declaration format is implemented.

## Link-layout constraint

Discovered source files are appended after the original FARM sources. Adding
real mod C files can change the overlay's linked layout. Before accepting such
a build, compare the linker map, symbol addresses, overlay size, and binary
against the original. Discovery alone does not prove that any memory is free
or that adding a source preserves original addresses.

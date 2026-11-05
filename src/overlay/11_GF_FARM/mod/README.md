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

## Hook registry

Edit `hooks.json` to register future JAL and function-entry hook requests.
The registry is intentionally empty until each original callsite/function,
expected instruction bytes, runtime address, and target symbol are verified.

## Link-layout constraint

Discovered source files are appended after the original FARM sources. Adding
real mod C files can change the overlay's linked layout. Before accepting such
a build, compare the linker map, symbol addresses, overlay size, and binary
against the original. Discovery alone does not prove that any memory is free
or that adding a source preserves original addresses.

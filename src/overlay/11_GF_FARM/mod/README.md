# FARM mod sources

C files placed directly in this directory are discovered by CMake at configure
time and appended after the original FARM source list. Their headers are
available through the FARM mod include path.

Example:
- mod_main.c / mod_main.h
- mod_rucksack.c / mod_rucksack.h
- mod_item_storage.c / mod_item_storage.h

## Hook registry

Edit `hooks.json` to register future JAL and function-entry hook requests.
The registry is intentionally empty until each original callsite/function,
expected instruction bytes, runtime address, and target symbol are verified.

Current status: C-source auto-discovery is wired into the FARM overlay build.
The registry is not yet consumed by the binary patch stage; no automatic
runtime patch is applied by this change.

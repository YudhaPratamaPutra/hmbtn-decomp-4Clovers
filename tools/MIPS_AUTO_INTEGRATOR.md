# MIPS Auto Integrator

## Stage 1 — MIPS-I/R3000 core

The reusable instruction core is in `tools/mips/core.py`. It provides:
- Strict field decoding for SPECIAL, REGIMM, common integer/branch/load/store
  instructions, and basic COP0/COP1/COP2 instruction classes.
- R/I/J and conditional-branch encoders with field, alignment, and range checks.
- Decoded signed/unsigned immediates, branch/jump destinations, and control
  transfer/delay-slot classification.
- Fail-closed handling: unknown or reserved encodings raise `MipsDecodeError`.

This is an instruction-field core, not a complete disassembler or assembler.
COP0/COP1/COP2 operation payloads are classified, not fully decoded. COP3,
reserved opcodes, and unimplemented SPECIAL/REGIMM encodings are rejected.

## Stage 2 — JAL Engine

The JAL engine is in `tools/mips/jal.py`:
- Scans aligned words and resolves opcode-3 JAL destinations using the runtime
  address supplied for byte zero of the image.
- Supports offset-range and target filters.
- Requires exact original instruction words and optionally the original target
  before planning a callsite replacement.
- Validates a complete batch before writing; duplicate offsets are rejected.
- Returns a new image and never mutates the input.

The scanner does not distinguish executable instructions from embedded data.
The caller must constrain scanning to a verified code range. No runtime base
address is inferred.

## Stage 3 — HOOK Engine

The HOOK engine is in `tools/mips/hook.py`. It plans and applies a function-entry
hook plus its trampoline within one supplied binary image.

The caller must explicitly provide:
- Site file offset and runtime PC.
- Hook runtime PC.
- Trampoline file offset and runtime PC.
- The exact two original instructions at the hook site.
- The exact 16 original bytes reserved for trampoline storage.

The engine replaces 8 bytes at the site with `j hook; nop`. The trampoline
contains the two displaced instructions followed by `j site+8; nop`. Both
regions are revalidated immediately before application. Site and trampoline
storage must be in-bounds, aligned, and non-overlapping. The output is a new
image; the input is not mutated.

Relocation is deliberately conservative: both displaced words must decode as
supported MIPS-I instructions and neither may be a control transfer. Unknown or
reserved instructions are rejected. The hook and return jumps must satisfy the
MIPS PC+4 256 MiB pseudo-direct region rule. The engine does not search for free
trampoline memory, infer load addresses, or prove that a supplied 16-byte area
is unused. That proof remains the caller's responsibility.

### HOOK CLI

Inspect a hook plan without modifying the input:

```sh
python3 tools/mips_auto_integrator.py hook-plan \
  --input overlay.bin \
  --site-offset 0x100 --site-pc 0x800B7F20 \
  --hook-pc 0x80030000 \
  --trampoline-offset 0x700 --trampoline-pc 0x800B8520 \
  --word0 0x27BDFFE8 --word1 0xAFBF0010 \
  --expected-trampoline CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC
```

Apply only after independently verifying both file offsets and runtime addresses:

```sh
python3 tools/mips_auto_integrator.py hook-apply \
  --input overlay.bin --output overlay.hooked.bin \
  --site-offset 0x100 --site-pc 0x800B7F20 \
  --hook-pc 0x80030000 \
  --trampoline-offset 0x700 --trampoline-pc 0x800B8520 \
  --word0 0x27BDFFE8 --word1 0xAFBF0010 \
  --expected-trampoline CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC
```

The hexadecimal trampoline guard must represent exactly 16 bytes. The example
addresses and bytes above are illustrative CLI syntax, not verified game
addresses or free storage.

## Stage 4 — Mod Discovery

The inventory API is in `tools/mips/discovery.py`. It recursively inventories
`mod/**/*.c` and `mod/**/*.h`, sorts paths deterministically, and validates
the existing version-1 `hooks.json` envelope (schema version, overlay name,
and hooks array). It reports the number of registered hooks but does not execute
or apply registry entries.

CMake's `psx_overlay_mod_sources()` now uses recursive, configure-dependent
discovery. Nested mod source files are compiled using their relative paths, so
the resulting object paths remain distinct. FARM's original source list remains
in its existing order; discovered mod sources are appended after `farm_vars.c`.
There are currently no actual mod C source files in the FARM mod directory, so
the recursive discovery change adds no new game objects by itself.

Run an inventory:

```sh
python3 tools/mips_auto_integrator.py mod-discover \
  --overlay src/overlay/11_GF_FARM --json
```

The discovery tool rejects a missing mod directory, malformed or incompatible
registry metadata, and symlinked source/header files. It does not determine
whether a mod function is safe to link into the original overlay, reserve memory,
resolve symbols, or alter game binaries.

## Remaining integration work

The three engines are still explicit-address tools. Linker-map symbol resolution,
registry-driven JAL/HOOK requests, automatic safe trampoline allocation, overlay
lifecycle integration, and binary/map regression validation remain future stages.

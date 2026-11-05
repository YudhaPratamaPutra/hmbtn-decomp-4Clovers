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
PS1 binary reads and writes remain little-endian in the patching layer.

## Stage 2 — JAL Engine

The JAL engine is in `tools/mips/jal.py` and is exposed through
`tools/mips_auto_integrator.py`:

- `scan_jal(data, base_address)` scans aligned 32-bit words and resolves JAL
  destinations using each callsite PC. The caller must supply the runtime address
  corresponding to byte zero; no load address is guessed.
- Optional byte-range and destination filters narrow the scan.
- `plan_jal_patch` requires the exact original instruction word and can also
  require the original destination before creating a patch record.
- `apply_jal_patches` validates the complete batch before writing any bytes,
  rejects duplicate offsets, and returns a new image without mutating the input.
- Replacement targets must be aligned and in the same 256 MiB pseudo-direct
  region as callsite PC+4.

The scanner identifies opcode-3 words in the requested range. It does not
distinguish executable instructions from embedded data; callers must constrain
the scan to a verified code range. This stage does not yet resolve function names
from linker maps or apply `hooks.json` registry entries.

### CLI

Scan a binary (base address maps to byte zero):

```sh
python3 tools/mips_auto_integrator.py jal-scan \
  --input overlay.bin --base 0x800B7E20
```

Filter by destination and/or range:

```sh
python3 tools/mips_auto_integrator.py jal-scan \
  --input overlay.bin --base 0x800B7E20 \
  --start 0x100 --end 0x4000 --target 0x800BBC34
```

Patch one verified callsite into a separate output file:

```sh
python3 tools/mips_auto_integrator.py jal-patch \
  --input overlay.bin --output overlay.patched.bin \
  --base 0x800B7E20 --offset 0x120 \
  --target 0x80030000 --expected-word 0x0C02EF00
```

The expected word must come from the exact original binary. Never use a guessed
word or address. The command writes the output only after all validation passes.

## Existing HOOK foundation

The companion module still provides a conservative two-instruction function
hook planner. Hook relocation rejects control-transfer instructions and does not
guess a trampoline address. Full HOOK integration is a later stage.

## Overlay mod source discovery

The FARM overlay calls `psx_overlay_mod_sources(farm_mod_sources)`.
CMake discovers every `src/overlay/11_GF_FARM/mod/*.c` file and appends it
after the existing FARM source list. The initial registry
`src/overlay/11_GF_FARM/mod/hooks.json` is intentionally empty. Registry-driven
patch application and symbol resolution are not implemented yet.

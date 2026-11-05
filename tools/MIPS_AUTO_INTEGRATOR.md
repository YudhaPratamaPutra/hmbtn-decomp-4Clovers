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

Run the stage tests:

```sh
python3 -m unittest tests.test_mips_core -v
python3 -m unittest tests.test_mips_auto_integrator -v
```

## Existing patch primitives

The companion `tools/mips_auto_integrator.py` currently provides JAL encode/decode,
expected-word guarded JAL patching, and a conservative two-instruction function
hook planner. Hook relocation rejects control-transfer instructions and does not
guess a trampoline address.

## Overlay mod source discovery

The FARM overlay calls `psx_overlay_mod_sources(farm_mod_sources)`.
CMake discovers every `src/overlay/11_GF_FARM/mod/*.c` file and appends it
after the existing FARM source list. The initial registry
`src/overlay/11_GF_FARM/mod/hooks.json` is intentionally empty. Registry-driven
patch application and symbol resolution are not implemented yet.

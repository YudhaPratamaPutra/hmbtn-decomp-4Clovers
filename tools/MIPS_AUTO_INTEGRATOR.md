# MIPS Auto Integrator (foundation)

Scope is intentionally limited to three primitives:

1. MIPS-I/R3000 JAL encode/decode.
2. JAL callsite patching with an expected-original-word guard.
3. Function-entry hook planning/application with a trampoline.

The PS1 image format is little-endian. All addresses supplied to the tool are
runtime virtual addresses; file offsets are separate inputs. The tool does not
guess a module load address or a free trampoline location.

## Safety constraints

- J/JAL targets must be aligned and in the same 256 MiB pseudo-direct region as PC+4.
- A function-entry hook replaces exactly two instructions (8 bytes): `j hook`,
  then `nop`.
- The trampoline copies those two displaced instructions and jumps back to site+8.
- The initial relocator rejects branch/jump instructions in the displaced pair.
  This is deliberately conservative; it does not yet relocate arbitrary PC-relative
  instructions or rewrite branch delay slots.
- Patching requires an exact match against the expected original instruction words.
- No patch is applied to game binaries by default; use a copy and validate output.

## CLI

```sh
python3 tools/mips_auto_integrator.py jal-encode --pc 0x80010000 --target 0x80023450
python3 tools/mips_auto_integrator.py jump-decode --pc 0x80010000 --word 0x0C008D14
python3 tools/mips_auto_integrator.py hook-plan --site 0x80012000 --hook 0x80024000 \
  --trampoline 0x80030000 --word0 0x27BDFFE8 --word1 0xAFBF0010
python3 -m unittest tests.test_mips_auto_integrator -v
```

This is a foundation, not a persistent runtime manager. Runtime overlay lifecycle
integration is intentionally out of scope until the loader path and module address
mapping are verified from the original source and binary.

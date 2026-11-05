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

## Stage 5 — Linker Map Symbol Resolver

The resolver is implemented in `tools/mips/symbols.py`. It reads GNU ld map
text and extracts rows containing a 32-bit hexadecimal address followed by an
exact symbol name. It retains source line numbers and all definitions.

Resolution rules:
- Symbol lookup is exact and case-sensitive.
- A missing symbol is an error.
- Repeated definitions at the same address are treated as consistent aliases.
- A name defined at multiple distinct addresses is ambiguous and rejected.
- Batch resolution fails as a whole if any requested name is missing or
  ambiguous; requested order is preserved and duplicate requests are rejected.
- No address is inferred from source order, object order, or nearby symbols.

The resolver currently handles ordinary C-style linker symbol names. It is not
a full GNU map grammar parser and does not resolve expressions, archive members,
or section-relative offsets. Its input must be the actual map generated by the
same build whose binary will be patched.

### CLI

List symbol rows extracted from the map:

```sh
python3 tools/mips_auto_integrator.py symbol-list \
  --map build/program.map --json
```

Resolve one or more exact names:

```sh
python3 tools/mips_auto_integrator.py symbol-resolve \
  --map build/program.map \
  --symbol farm_enter_dispatch \
  --symbol item_merge_dispatch --json
```

The output includes symbol addresses and map line numbers. The map must belong
to the exact linked image being inspected.

## Stage 6 — Registry-driven Auto Integration

The integration pipeline is in `tools/mips/integration.py`. It connects the
registry, exact linker-map symbols, JAL planner, and HOOK planner. It has two
commands:

Plan only; this does not write a binary:

```sh
python3 tools/mips_auto_integrator.py integrate-plan \
  --input build/11_GF_FARM.bin --base 0x800B0000 \
  --overlay 11_GF_FARM \
  --registry src/overlay/11_GF_FARM/mod/hooks.json \
  --map build/program.map
```

Apply after reviewing the plan and independently verifying the image/map pair:

```sh
python3 tools/mips_auto_integrator.py integrate-apply \
  --input build/11_GF_FARM.bin --output build/11_GF_FARM.patched.bin \
  --base 0x800B0000 --overlay 11_GF_FARM \
  --registry src/overlay/11_GF_FARM/mod/hooks.json \
  --map build/program.map
```

The base address is the explicitly supplied runtime address for byte zero of
the input image. Registry offsets are file offsets from that same byte zero.
The pipeline checks that each site symbol's map address equals
`base + file_offset`; hook trampoline runtime address is likewise calculated
only from the explicit image mapping and trampoline file offset.

Version-1 registry entries are strict; unknown or missing keys are rejected.
A JAL entry has this shape:

```json
{
  "id": "call-example",
  "type": "jal",
  "site_symbol": "verified_callsite_symbol",
  "file_offset": "0x120",
  "expected_word": "0x0C000000",
  "expected_target": "0x80000000",
  "target_symbol": "verified_target_symbol"
}
```

A HOOK entry has this shape:

```json
{
  "id": "entry-example",
  "type": "hook",
  "site_symbol": "verified_function_symbol",
  "site_offset": "0x200",
  "hook_symbol": "linked_mod_entry_symbol",
  "trampoline_offset": "0x700",
  "expected_words": ["0x27BDFFE8", "0xAFBF0010"],
  "expected_trampoline": "CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC"
}
```

These values illustrate the schema only; they are not game addresses, verified
instructions, or a declaration that trampoline storage is free. Do not add a
registry entry until the exact map symbols, file offsets, original instruction
words, and 16-byte trampoline region have been independently established.

Planning validates every entry before producing a plan. It rejects missing or
ambiguous symbols, symbol/file mapping mismatches, original-byte mismatches,
unsupported displaced instructions, invalid jump regions, duplicate IDs, and
overlapping patch regions. The plan records the input image SHA-256. Apply
rebuilds the plan from the current registry and map and refuses if the plan or
input image has changed; it writes a separate output image and leaves the input
untouched.

The pipeline does not search for or allocate trampoline space, prove that a
reserved region is unused, infer overlay load addresses, or validate the final
linker map/binary layout after patching. Those remain explicit verification
tasks. The FARM registry currently has an empty `hooks` array, so integration
currently produces a valid no-op plan; no game binary is modified until
verified entries are added.


## Stage 7 — Post-integration Validation Engine

The validation engine is implemented in `tools/mips/validation.py`. It
compares the original image, patched output, and the exact `IntegrationPlan`
built from the original image and current registry/map inputs.

It verifies:
- The original image SHA-256 matches the plan.
- Original and patched image sizes are identical.
- Every planned JAL replacement word matches the output.
- Every planned HOOK site and trampoline byte sequence matches the output.
- The authorized patch ranges do not overlap.
- Every changed byte is contained within one of those authorized ranges.
- Bytes outside the authorized ranges remain identical to the original image.

The validator is read-only. It does not repair output, infer patch ranges,
validate whether trampoline storage is semantically unused, or prove that the
linked map and binary were produced by the same build beyond the explicit
symbol/address and original-image checks already performed by the integration
pipeline. Linker-map and binary layout comparisons remain a separate build
verification responsibility.

Validate an existing patched image:

```sh
python3 tools/mips_auto_integrator.py integrate-validate \\
  --input build/11_GF_FARM.bin \\
  --patched build/11_GF_FARM.patched.bin \\
  --base 0x800B0000 --overlay 11_GF_FARM \\
  --registry src/overlay/11_GF_FARM/mod/hooks.json \\
  --map build/program.map
```

The command rebuilds the plan from the supplied original image, registry, and
map, then validates the supplied patched image against that plan. It emits
SHA-256 values, image size, authorized patch ranges, and actual changed ranges.
A failed check raises a validation error; the validator never modifies either
input file.

The FARM registry currently contains no registered hooks, so its current
validation plan is a no-op: only an output byte-for-byte identical to the
original image is valid.



## Stage 11 — HOOK Integration into the Overlay Image

The HOOK registry produced in Stage 10 is consumed by the same
`build_integration_plan()` and `apply_integration_plan()` pipeline as JAL.
For each HOOK entry, the planner resolves the exact site, hook function,
trampoline symbol, and linker-reserved trampoline section from the map.
It rejects a trampoline outside that reserved section and checks the
original two site words and all 16 trampoline bytes against the supplied
overlay image.

Applying the plan writes the two-word jump at the registered site and the
four-word trampoline at the declared trampoline offset. The generated
sidecar overlay is then checked by `validate_integrated_image()`, which
permits changes only in the registered eight-byte hook site and sixteen-byte
trampoline range. The original overlay remains the input and is not replaced.

The existing CMake target `mips-integrate-farm` connects discovery,
HOOK/JAL registration, `integrate-apply`, and `integrate-validate`.
Its output is `build/11_GF_FARM.mod.bin`; the original
`build/11_GF_FARM.bin` remains unchanged.

## Stage 9 — MIPS Instruction Analysis

The sequential scanner and decoder are connected through
`tools/mips/analysis.py`. The analyzer uses the MIPS-I/R3000 decoder in
`tools/mips/core.py` over an explicitly selected, aligned file range and an
explicit runtime base address. It reports decoded instruction fields and
direct branch/J/JAL references. Unsupported words are retained as undecoded
records so the scan can continue; they are not treated as instructions.

Run analysis without modifying the image:

```sh
python3 tools/mips_auto_integrator.py mips-analyze \
  --input build/11_GF_FARM.bin --base 0x800B7E20 \
  --start 0x0 --end 0x1000
```

The integration planner also runs the analyzer on each explicitly registered
JAL or HOOK site and includes the decoded instruction/reference report in that
entry's plan. The registry remains the sole source of patch targets: analysis
references are diagnostic information and never create registry entries or
patches automatically. The scanner does not infer code/data boundaries, so
callers must provide a verified range when analyzing an image containing data.



## Stage 10 — HOOK Declaration Discovery and Registration

The `hook-discover` command scans `mod/**/*.c` for explicit
`MIPS_AUTO_HOOK` block-comment declarations. Each declaration identifies
its exact `site_symbol` and linker-reserved `trampoline_symbol`; the
function definition immediately following the declaration supplies the
mod hook function symbol.

The `hook-register` command resolves those symbols and the overlay-specific
`__mips_trampoline_start_<overlay>` / `__mips_trampoline_end_<overlay>`
bounds from the supplied linker map. It derives file offsets from the
explicit image base and reads original instruction and trampoline guards
from the exact linked overlay image. It writes the resulting HOOK entries
to the schema-v1 registry while preserving existing JAL entries.

Example:

```sh
python3 tools/mips_auto_integrator.py hook-discover \
  --overlay src/overlay/11_GF_FARM --json

python3 tools/mips_auto_integrator.py hook-register \
  --overlay src/overlay/11_GF_FARM \
  --map build/program.map --input build/11_GF_FARM.bin \
  --base 0x800B7E20
```

The generated registry is consumed by the existing integration planner.
Discovery never chooses a site from a scan result, and registration does not
patch the image. A HOOK declaration is accepted only when its symbols,
reserved trampoline range, source image bytes, and non-overlapping patch
ranges are all represented by the supplied build inputs.

## Stage 8 — CMake Build Integration

The root CMake configuration exposes an explicit `mips-integrate-farm`
target. It depends on the normal `program` target, so the linker map and
original FARM overlay are generated by the same build before integration runs.

Run the normal build first, then invoke the sidecar integration target:

```sh
cmake --build build
cmake --build build --target mips-integrate-farm
```

The target uses:
- `build/11_GF_FARM.bin` as the unmodified input overlay.
- `build/program.map` as the linker map from that build.
- Runtime base `0x800B7E20`, the configured start of the `low` overlay region.
- `src/overlay/11_GF_FARM/mod/hooks.json` as the integration registry.

It writes `build/11_GF_FARM.mod.bin` as a separate sidecar, then runs the
Stage 7 validator against the original overlay and that sidecar. It never
replaces `11_GF_FARM.bin`, the generated executable, or the disc/A_FILE.
The target is not part of the default build and must be requested explicitly.

The FARM registry currently has no entries. Therefore the current sidecar is
expected to be byte-identical to the original overlay. This target connects the
existing plan/apply/validate pipeline to CMake; it does not establish that any
trampoline region is free, add game hooks, or prove runtime behavior. A real
mod integration still requires verified registry entries and a review of the
linker map and binary layout before applying patches.


## Stage 12 — Build Pipeline per Overlay

CMake now creates an opt-in `mips-integrate-<overlay>` target for every
registered overlay that has a `mod/` directory. The target derives the overlay
binary filename and runtime base from the existing `psx_overlay()` metadata
and its configured load region; it does not hardcode FARM addresses.

The normal `program` dependency compiles the overlay's discovered mod C
sources and produces the matching `program.map` and original overlay BIN.
The per-overlay target then runs, in order:

1. Overlay inventory discovery.
2. Mod C/header discovery.
3. MIPS instruction analysis of the exact overlay image.
4. JAL and HOOK declaration discovery.
5. HOOK and JAL registry generation using the same linker map and overlay BIN.
6. Integration planning.
7. Integration apply to a separate `<overlay>.mod.bin` sidecar.
8. Integration validation against the original overlay.

For the current FARM mod directory, invoke:

```sh
cmake --build build --target mips-integrate-11_GF_FARM
```

The target is opt-in and is not part of the default build. The original overlay
BIN, program ELF, and A_FILE are not replaced. Future overlays gain the same
pipeline by adding a `mod/` directory and using the existing `psx_overlay()`
declaration; no FARM-specific CMake integration block is required.

## Stage 13 — Connect the Pipeline to CMake Packaging

The root CMake file registers per-overlay integration targets after including
`cmake/disc.cmake`. This ensures the `afile` target already exists when the
integration targets are connected.

For each overlay with a `mod/` directory,
`psx_overlay_mips_integration_targets()` adds a dependency from `afile` to
`mips-integrate-<overlay>`. Each integration target itself depends on
`program`, which builds the matching overlay image and shared linker map.
The dependency chain is:

```text
program
  └─ mips-integrate-<overlay>
       └─ afile packaging
```

The dependency is created for every eligible overlay, not just FARM. There is
no separate manual FARM target invocation. When `ORIGINAL_DISC` is not set,
`disc.cmake` does not create `afile`; the per-overlay integration targets
remain available as explicit build targets.
## Stage 14 — Package Integrated Overlay Binaries into A_FILE

`tools/afile.py pack` accepts an integrated-binary directory and an explicit
member list. Only filenames listed in that manifest are read from the integrated
directory; all other `built` members continue to come from the normal build
directory, and `original` members continue to come from the translated original
directory.

`psx_overlay_mips_integration_targets()` writes the manifest for overlays with
`mod/` directories. After validating each sidecar, its target copies the sidecar
to `integrated_A_FILE/<A_FILE member filename>`. `cmake/disc.cmake` passes this
directory and manifest to `afile.py pack`, and declares the manifest as a build
dependency. The original linked overlay BIN is not overwritten.

The packaging unit tests verify that a listed member comes from the integrated
sidecar, unlisted built members remain sourced from the build directory, and
original members remain sourced from the original directory.
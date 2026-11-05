#!/usr/bin/env python3
"""Small, fail-closed MIPS-I/R3000 JAL and function-entry hook toolkit.

PS1 binaries are little-endian. This module only emits absolute J/JAL transfers
within the MIPS 256 MiB pseudo-direct region. Hook relocation is deliberately
limited to two ordinary, position-independent instructions.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

# Allow direct execution from any working directory (including GitHub Actions).
# The script lives in <repo>/tools/, while package imports use tools.mips.*.
REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

MASK32 = 0xFFFFFFFF


class MipsPatchError(ValueError):
    pass


def _u32(value: int) -> int:
    return value & MASK32


def encode_jal(pc: int, target: int) -> int:
    """Encode JAL at pc; target must share the high 4 bits of pc+4."""
    if pc & 3 or target & 3:
        raise MipsPatchError("PC and target must be 4-byte aligned")
    if ((pc + 4) & 0xF0000000) != (target & 0xF0000000):
        raise MipsPatchError("JAL target is outside the 256 MiB pseudo-direct region")
    return 0x0C000000 | ((target >> 2) & 0x03FFFFFF)


def encode_j(pc: int, target: int) -> int:
    if pc & 3 or target & 3:
        raise MipsPatchError("PC and target must be 4-byte aligned")
    if ((pc + 4) & 0xF0000000) != (target & 0xF0000000):
        raise MipsPatchError("J target is outside the 256 MiB pseudo-direct region")
    return 0x08000000 | ((target >> 2) & 0x03FFFFFF)


def decode_jump(pc: int, instruction: int) -> dict:
    opcode = (instruction >> 26) & 0x3F
    if opcode not in (2, 3):
        raise MipsPatchError(f"instruction opcode {opcode} is not J/JAL")
    target = (((pc + 4) & 0xF0000000) | ((instruction & 0x03FFFFFF) << 2))
    return {"kind": "JAL" if opcode == 3 else "J", "pc": _u32(pc),
            "target": _u32(target), "instruction": _u32(instruction)}


def _is_control_or_pc_relative(word: int) -> bool:
    op = (word >> 26) & 0x3F
    if op in (1, 2, 3, 4, 5, 6, 7, 20, 21, 22, 23):
        return True  # REGIMM, J/JAL, conditional branches (incl. likely)
    if op in (16, 17, 18, 19):
        return ((word >> 21) & 0x1F) == 8  # COP branch
    if op == 0 and (word & 0x3F) in (8, 9):
        return True  # JR/JALR
    return False


def _pack_words(words: tuple[int, ...]) -> bytes:
    return struct.pack("<" + "I" * len(words), *(_u32(w) for w in words))


def _read_words(data: bytes, offset: int, count: int) -> tuple[int, ...]:
    end = offset + count * 4
    if offset < 0 or end > len(data) or offset & 3:
        raise MipsPatchError("instruction range is unaligned or outside the file")
    return struct.unpack_from("<" + "I" * count, data, offset)


@dataclass(frozen=True)
class HookPlan:
    site: int
    hook: int
    trampoline: int
    original_words: tuple[int, int]
    patch_words: tuple[int, int]
    trampoline_words: tuple[int, int, int, int]

    def to_json(self) -> str:
        obj = asdict(self)
        for key in ("original_words", "patch_words", "trampoline_words"):
            obj[key] = [f"0x{x:08X}" for x in obj[key]]
        for key in ("site", "hook", "trampoline"):
            obj[key] = f"0x{obj[key]:08X}"
        return json.dumps(obj, indent=2)


def make_hook_plan(site: int, hook: int, trampoline: int,
                   original_words: tuple[int, int]) -> HookPlan:
    """Plan a 2-word entry hook and a 2-word displaced-instruction trampoline."""
    if site & 3 or hook & 3 or trampoline & 3:
        raise MipsPatchError("site, hook, and trampoline must be 4-byte aligned")
    if len(original_words) != 2:
        raise MipsPatchError("exactly two original instructions are required")
    if any(_is_control_or_pc_relative(w) for w in original_words):
        raise MipsPatchError(
            "cannot relocate branch/jump instruction; choose a different hook site"
        )
    patch = (encode_j(site, hook), 0)  # J hook; NOP delay slot
    back_pc = trampoline + 8
    back_jump = encode_j(back_pc, site + 8)
    tramp = (original_words[0], original_words[1], back_jump, 0)
    return HookPlan(site, hook, trampoline, original_words, patch, tramp)


def apply_hook(data: bytes, file_offset: int, plan: HookPlan,
               expected_words: tuple[int, int]) -> tuple[bytes, bytes]:
    """Return (patched_image, trampoline_bytes); never mutates input."""
    actual = _read_words(data, file_offset, 2)
    if actual != expected_words or actual != plan.original_words:
        raise MipsPatchError(
            f"original-byte check failed: found {[hex(x) for x in actual]}"
        )
    patched = bytearray(data)
    patched[file_offset:file_offset + 8] = _pack_words(plan.patch_words)
    return bytes(patched), _pack_words(plan.trampoline_words)


def apply_jal(data: bytes, file_offset: int, pc: int, target: int,
              expected_word: int) -> bytes:
    actual = _read_words(data, file_offset, 1)[0]
    if actual != expected_word:
        raise MipsPatchError(
            f"original-byte check failed: found 0x{actual:08X}, "
            f"expected 0x{expected_word:08X}"
        )
    patched = bytearray(data)
    struct.pack_into("<I", patched, file_offset, encode_jal(pc, target))
    return bytes(patched)


def _int(s: str) -> int:
    return int(s, 0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("jal-encode")
    p.add_argument("--pc", required=True, type=_int)
    p.add_argument("--target", required=True, type=_int)
    p = sub.add_parser("jump-decode")
    p.add_argument("--pc", required=True, type=_int)
    p.add_argument("--word", required=True, type=_int)
    p = sub.add_parser("mips-analyze")
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--base", required=True, type=_int,
                   help="runtime address mapped to byte zero of input")
    p.add_argument("--start", type=_int, default=0)
    p.add_argument("--end", type=_int)
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("jal-scan")
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--base", required=True, type=_int,
                   help="runtime address mapped to byte zero of input")
    p.add_argument("--start", type=_int, default=0)
    p.add_argument("--end", type=_int)
    p.add_argument("--target", type=_int)
    p = sub.add_parser("jal-patch")
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--base", required=True, type=_int,
                   help="runtime address mapped to byte zero of input")
    p.add_argument("--offset", required=True, type=_int,
                   help="file offset of the JAL instruction")
    p.add_argument("--target", required=True, type=_int,
                   help="replacement runtime target")
    p.add_argument("--expected-word", required=True, type=_int)
    p.add_argument("--expected-target", type=_int)
    for command in ("hook-plan", "hook-apply"):
        p = sub.add_parser(command)
        p.add_argument("--input", required=True, type=Path)
        if command == "hook-apply":
            p.add_argument("--output", required=True, type=Path)
        p.add_argument("--site-offset", required=True, type=_int)
        p.add_argument("--site-pc", required=True, type=_int)
        p.add_argument("--hook-pc", required=True, type=_int)
        p.add_argument("--trampoline-offset", required=True, type=_int)
        p.add_argument("--trampoline-pc", required=True, type=_int)
        p.add_argument("--word0", required=True, type=_int)
        p.add_argument("--word1", required=True, type=_int)
        p.add_argument("--expected-trampoline", required=True,
                       help="exact 16-byte trampoline storage as 32 hex characters")
    p = sub.add_parser("overlay-discover")
    p.add_argument("--root", required=True, type=Path,
                   help="src/overlay directory containing overlay subdirectories")
    p.add_argument("--json", action="store_true",
                   help="emit machine-readable overlay inventory")
    p = sub.add_parser("mod-discover")
    p.add_argument("--overlay", required=True, type=Path,
                   help="overlay directory containing mod/")
    p.add_argument("--json", action="store_true",
                   help="emit machine-readable JSON")
    p = sub.add_parser("hook-discover")
    p.add_argument("--overlay", required=True, type=Path,
                   help="overlay directory containing mod/**/*.c")
    p.add_argument("--json", action="store_true",
                   help="emit machine-readable hook declarations")
    p = sub.add_parser("hook-register")
    p.add_argument("--overlay", required=True, type=Path,
                   help="overlay directory containing mod/**/*.c")
    p.add_argument("--map", required=True, type=Path, help="matching GNU ld program.map")
    p.add_argument("--input", required=True, type=Path, help="exact linked overlay image")
    p.add_argument("--base", required=True, type=_int,
                   help="runtime address mapped to byte zero of the image")
    p.add_argument("--output", type=Path,
                   help="registry output path (default: <overlay>/mod/hooks.json)")
    p = sub.add_parser("jal-discover")
    p.add_argument("--overlay", required=True, type=Path,
                   help="overlay directory containing mod/**/*.c")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("jal-register")
    p.add_argument("--overlay", required=True, type=Path,
                   help="overlay directory containing mod/**/*.c")
    p.add_argument("--map", required=True, type=Path, help="matching GNU ld program.map")
    p.add_argument("--input", required=True, type=Path, help="exact linked overlay image")
    p.add_argument("--base", required=True, type=_int,
                   help="runtime address mapped to byte zero of the image")
    p.add_argument("--output", type=Path,
                   help="registry output path (default: <overlay>/mod/hooks.json)")
    p = sub.add_parser("symbol-resolve")
    p.add_argument("--map", required=True, type=Path, help="GNU ld program.map")
    p.add_argument("--symbol", action="append", required=True,
                   help="exact symbol name; may be repeated")
    p.add_argument("--json", action="store_true", help="emit JSON")
    p = sub.add_parser("symbol-list")
    p.add_argument("--map", required=True, type=Path, help="GNU ld program.map")
    p.add_argument("--json", action="store_true", help="emit JSON")
    for command in ("integrate-plan", "integrate-apply", "integrate-validate"):
        p = sub.add_parser(command)
        p.add_argument("--input", required=True, type=Path, help="exact overlay image to inspect")
        p.add_argument("--base", required=True, type=_int,
                       help="runtime address mapped to byte zero of the image")
        p.add_argument("--overlay", required=True, help="overlay/module name")
        p.add_argument("--registry", required=True, type=Path, help="hooks.json")
        p.add_argument("--map", required=True, type=Path, help="matching GNU ld map")
        if command == "integrate-apply":
            p.add_argument("--output", required=True, type=Path)
        if command == "integrate-validate":
            p.add_argument("--patched", required=True, type=Path, help="patched image to validate")
    args = parser.parse_args()
    if args.cmd == "jal-encode":
        print(f"0x{encode_jal(args.pc, args.target):08X}")
    elif args.cmd == "jump-decode":
        print(json.dumps(decode_jump(args.pc, args.word), indent=2))
    elif args.cmd == "mips-analyze":
        from tools.mips.analysis import analyze_mips_image
        report = analyze_mips_image(
            args.input.read_bytes(), args.base,
            start_offset=args.start, end_offset=args.end,
        )
        print(json.dumps(report.to_dict(), indent=2))
    elif args.cmd == "jal-scan":
        from tools.mips.jal import scan_jal
        found = scan_jal(args.input.read_bytes(), args.base,
                         start_offset=args.start, end_offset=args.end,
                         target=args.target)
        print(json.dumps([item.to_dict() for item in found], indent=2))
    elif args.cmd == "jal-patch":
        from tools.mips.jal import apply_jal_patches, plan_jal_patch
        image = args.input.read_bytes()
        patch = plan_jal_patch(
            image, args.offset, args.base, args.target,
            expected_word=args.expected_word,
            expected_target=args.expected_target,
        )
        output = apply_jal_patches(image, [patch])
        args.output.write_bytes(output)
        print(json.dumps(patch.to_dict(), indent=2))
    elif args.cmd in ("hook-plan", "hook-apply"):
        from tools.mips.hook import apply_hook_patch, hook_plan_to_json, plan_hook_patch
        image = args.input.read_bytes()
        try:
            expected_trampoline = bytes.fromhex(args.expected_trampoline)
        except ValueError as exc:
            parser.error(f"invalid --expected-trampoline hex: {exc}")
        plan = plan_hook_patch(
            image, site_offset=args.site_offset, site_pc=args.site_pc,
            hook_pc=args.hook_pc, trampoline_offset=args.trampoline_offset,
            trampoline_pc=args.trampoline_pc,
            expected_original_words=(args.word0, args.word1),
            expected_trampoline=expected_trampoline,
        )
        if args.cmd == "hook-plan":
            print(hook_plan_to_json(plan))
        else:
            args.output.write_bytes(apply_hook_patch(image, plan))
            print(hook_plan_to_json(plan))
    elif args.cmd in ("symbol-resolve", "symbol-list"):
        from tools.mips.symbols import load_linker_map, resolve_symbols
        symbol_table = load_linker_map(args.map)
        if args.cmd == "symbol-resolve":
            resolved = resolve_symbols(symbol_table, args.symbol)
            if args.json:
                print(json.dumps([item.to_dict() for item in resolved], indent=2))
            else:
                print("\\n".join(
                    f"{item.name}=0x{item.address:08X}" for item in resolved
                ))
        else:
            rows = [
                {"symbol": name, "definitions": [
                    {"address": f"0x{item.address:08X}", "line": item.line}
                    for item in definitions
                ]}
                for name, definitions in sorted(symbol_table.items())
            ]
            if args.json:
                print(json.dumps(rows, indent=2))
            else:
                for row in rows:
                    addresses = ", ".join(item["address"] for item in row["definitions"])
                    print(f"{row['symbol']}: {addresses}")
    elif args.cmd in ("integrate-plan", "integrate-apply", "integrate-validate"):
        from tools.mips.integration import (
            apply_integration_plan, build_integration_plan,
        )
        if args.cmd == "integrate-apply":
            print("[MIPS AUTO INTEGRATOR] INTEGRATION START")
        elif args.cmd == "integrate-validate":
            print("[MIPS AUTO INTEGRATOR] VALIDATION START")
        image = args.input.read_bytes()
        plan = build_integration_plan(
            image, base_address=args.base, overlay=args.overlay,
            registry_path=args.registry, map_path=args.map,
        )
        if args.cmd == "integrate-plan":
            print(json.dumps(plan.to_dict(), indent=2))
        elif args.cmd == "integrate-validate":
            from tools.mips.validation import validate_integrated_image
            report = validate_integrated_image(image, args.patched.read_bytes(), plan)
            print("[MIPS AUTO INTEGRATOR] VALIDATION PASS")
            print(f"  Overlay: {plan.overlay}")
            print(f"  Registry entries: {len(plan.entries)}")
            print(f"  Image size: {report.image_size} bytes")
            print(f"  Authorized ranges: {len(report.authorized_ranges)}")
            print(f"  Changed ranges: {len(report.changed_ranges)}")
            print(f"  Original SHA-256: {report.original_sha256}")
            print(f"  Output SHA-256:   {report.output_sha256}")
        else:
            print(f"[MIPS AUTO INTEGRATOR] PLAN READY - {len(plan.entries)} registry entries")
            output = apply_integration_plan(
                image, plan, base_address=args.base, overlay=args.overlay,
                registry_path=args.registry, map_path=args.map,
            )
            args.output.write_bytes(output)
            output_sha256 = __import__("hashlib").sha256(output).hexdigest()
            print("[MIPS AUTO INTEGRATOR] INTEGRATION COMPLETE")
            print(f"  Overlay: {plan.overlay}")
            print(f"  Registry entries: {len(plan.entries)}")
            print(f"  Output: {args.output}")
            print(f"  Input SHA-256:  {plan.image_sha256}")
            print(f"  Output SHA-256: {output_sha256}")
    elif args.cmd == "hook-discover":
        from tools.mips.declarations import discover_hook_declarations
        declarations = discover_hook_declarations(args.overlay)
        payload = [item.to_dict() for item in declarations]
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"[MIPS AUTO INTEGRATOR] HOOK DECLARATIONS - {len(payload)}")
            for item in payload:
                print(
                    f"  {item['id']}: {item['hook_symbol']} -> "
                    f"{item['site_symbol']} ({item['source']}:{item['line']})"
                )
    elif args.cmd == "hook-register":
        from tools.mips.registration import write_hook_registry
        output_path = args.output or (args.overlay / "mod" / "hooks.json")
        registry = write_hook_registry(
            args.overlay, output_path,
            map_path=args.map, image_path=args.input,
            base_address=args.base,
        )
        print("[MIPS AUTO INTEGRATOR] HOOK REGISTRATION COMPLETE")
        print(f"  Overlay: {registry['module']}")
        print(f"  Registry: {output_path}")
        print(f"  Registered hooks: {len(registry['hooks'])}")
    elif args.cmd == "jal-discover":
        from tools.mips.jal_declarations import discover_jal_declarations
        declarations = discover_jal_declarations(args.overlay)
        payload = [item.to_dict() for item in declarations]
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"[MIPS AUTO INTEGRATOR] JAL DECLARATIONS - {len(payload)}")
            for item in payload:
                print(f"  {item['id']}: {item['site_symbol']} -> {item['target_symbol']} ({item['source']}:{item['line']})")
    elif args.cmd == "jal-register":
        from tools.mips.jal_registration import write_jal_registry
        output_path = args.output or (args.overlay / "mod" / "hooks.json")
        registry = write_jal_registry(
            args.overlay, output_path,
            map_path=args.map, image_path=args.input,
            base_address=args.base,
        )
        jal_count = sum(1 for item in registry["hooks"] if item["type"] == "jal")
        print("[MIPS AUTO INTEGRATOR] JAL REGISTRATION COMPLETE")
        print(f"  Overlay: {registry['module']}")
        print(f"  Registry: {output_path}")
        print(f"  Registered JAL entries: {jal_count}")
    elif args.cmd == "overlay-discover":
        from tools.mips.discovery import discover_overlays
        overlays = discover_overlays(args.root)
        payload = [item.to_dict() for item in overlays]
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"[MIPS AUTO INTEGRATOR] OVERLAY DISCOVERY - {len(payload)}")
            for item in payload:
                print(
                    f"  {item['overlay']}: mod={item['has_mod_directory']}, "
                    f"C={item['source_count']}, H={item['header_count']}"
                )
    elif args.cmd == "mod-discover":
        from tools.mips.discovery import discover_mod_sources
        if not args.json:
            print(f"[MIPS AUTO INTEGRATOR] DISCOVERY START - {args.overlay.name}")
        inventory = discover_mod_sources(args.overlay)
        if args.json:
            print(json.dumps(inventory.to_dict(), indent=2))
        else:
            print(f"[MIPS AUTO INTEGRATOR] OVERLAY - {inventory.overlay}")
            print("[MIPS AUTO INTEGRATOR] DISCOVERY COMPLETE")
            print(f"  C sources: {len(inventory.sources)}")
            for source in inventory.sources:
                print(f"    {source}")
            print(f"  Headers: {len(inventory.headers)}")
            for header in inventory.headers:
                print(f"    {header}")
            if inventory.registry_path:
                print(
                    f"  Hook registry: {inventory.registry_path} "
                    f"({inventory.registry_hooks} entries)"
                )
            else:
                print("  Hook registry: not present")


if __name__ == "__main__":
    main()

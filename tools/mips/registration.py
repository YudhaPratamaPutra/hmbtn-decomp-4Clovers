"""Generate the V9 hook registry from explicit declarations and verified build inputs.

The generator resolves symbols from the supplied linker map, derives only the
site file offset from the supplied image base, and reads all byte guards from
the exact supplied image. Trampoline placement remains an explicit declaration.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

from .declarations import HookDeclarationError, discover_hook_declarations
from .hook import HookEngineError, plan_hook_patch
from .symbols import SymbolResolverError, load_linker_map, resolve_symbol


class HookRegistrationError(ValueError):
    pass


def generate_hook_registry(
    overlay_dir: str | Path,
    *,
    map_path: str | Path,
    image_path: str | Path,
    base_address: int,
) -> dict[str, Any]:
    """Build a schema-v1 hooks registry; fail closed on incomplete declarations."""
    if isinstance(base_address, bool) or not isinstance(base_address, int):
        raise HookRegistrationError("base_address must be an integer")
    if not 0 <= base_address <= 0xFFFFFFFF or base_address & 3:
        raise HookRegistrationError("base_address must be an aligned unsigned 32-bit address")

    overlay = Path(overlay_dir)
    if not overlay.is_dir():
        raise HookRegistrationError(f"overlay directory does not exist: {overlay_dir}")
    module = overlay.name
    image_file = Path(image_path)
    try:
        image = image_file.read_bytes()
    except OSError as exc:
        raise HookRegistrationError(f"cannot read overlay image {image_file}: {exc}") from exc
    if not image:
        raise HookRegistrationError("overlay image is empty")
    image_end = base_address + len(image)
    if image_end > 0x100000000:
        raise HookRegistrationError("image mapping exceeds the 32-bit address space")

    try:
        declarations = discover_hook_declarations(overlay)
        symbols = load_linker_map(map_path)
    except (HookDeclarationError, SymbolResolverError) as exc:
        raise HookRegistrationError(str(exc)) from exc

    hooks: list[dict[str, Any]] = []
    occupied: list[tuple[int, int, str]] = []
    for declaration in declarations:
        if declaration.trampoline_offset is None:
            raise HookRegistrationError(
                f"{declaration.source}:{declaration.line}: declaration "
                f"{declaration.declaration_id!r} must specify trampoline_offset"
            )
        try:
            site = resolve_symbol(symbols, declaration.site_symbol)
            hook = resolve_symbol(symbols, declaration.hook_symbol)
        except SymbolResolverError as exc:
            raise HookRegistrationError(
                f"{declaration.declaration_id}: {exc}"
            ) from exc

        if not base_address <= site.address < image_end:
            raise HookRegistrationError(
                f"{declaration.declaration_id}: site symbol address "
                f"0x{site.address:08X} is outside the supplied image mapping"
            )
        if not base_address <= hook.address < image_end:
            raise HookRegistrationError(
                f"{declaration.declaration_id}: hook symbol address "
                f"0x{hook.address:08X} is outside the supplied image mapping"
            )

        site_offset = site.address - base_address
        trampoline_offset = declaration.trampoline_offset
        if site_offset & 3 or trampoline_offset & 3:
            raise HookRegistrationError(
                f"{declaration.declaration_id}: derived site or declared trampoline "
                "offset is not 4-byte aligned"
            )
        if site_offset + 8 > len(image):
            raise HookRegistrationError(
                f"{declaration.declaration_id}: hook site extends beyond supplied image"
            )
        if trampoline_offset + 16 > len(image):
            raise HookRegistrationError(
                f"{declaration.declaration_id}: trampoline range extends beyond supplied image"
            )

        original_words = struct.unpack_from("<2I", image, site_offset)
        trampoline_guard = image[trampoline_offset:trampoline_offset + 16]
        try:
            plan_hook_patch(
                image,
                site_offset=site_offset,
                site_pc=site.address,
                hook_pc=hook.address,
                trampoline_offset=trampoline_offset,
                trampoline_pc=base_address + trampoline_offset,
                expected_original_words=original_words,
                expected_trampoline=trampoline_guard,
            )
        except HookEngineError as exc:
            raise HookRegistrationError(
                f"{declaration.declaration_id}: {exc}"
            ) from exc

        occupied.extend([
            (site_offset, site_offset + 8, declaration.declaration_id + ":site"),
            (trampoline_offset, trampoline_offset + 16,
             declaration.declaration_id + ":trampoline"),
        ])
        hooks.append({
            "id": declaration.declaration_id,
            "type": "hook",
            "site_symbol": declaration.site_symbol,
            "site_offset": f"0x{site_offset:X}",
            "hook_symbol": declaration.hook_symbol,
            "trampoline_offset": f"0x{trampoline_offset:X}",
            "expected_words": [f"0x{word:08X}" for word in original_words],
            "expected_trampoline": trampoline_guard.hex(),
        })

    occupied.sort()
    for previous, current in zip(occupied, occupied[1:]):
        if current[0] < previous[1]:
            raise HookRegistrationError(
                f"patch regions overlap: {previous[2]} and {current[2]}"
            )

    return {"schema_version": 1, "module": module, "hooks": hooks}


def write_hook_registry(
    overlay_dir: str | Path,
    output_path: str | Path,
    *,
    map_path: str | Path,
    image_path: str | Path,
    base_address: int,
) -> dict[str, Any]:
    """Generate completely before replacing the requested registry file."""
    registry = generate_hook_registry(
        overlay_dir,
        map_path=map_path,
        image_path=image_path,
        base_address=base_address,
    )
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(registry, indent=2) + "\n"
    temporary = destination.with_name(destination.name + ".tmp")
    try:
        temporary.write_text(serialized, encoding="utf-8")
        temporary.replace(destination)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise HookRegistrationError(
            f"cannot write generated registry {destination}: {exc}"
        ) from exc
    return registry

"""Generate JAL registry entries from explicit source declarations and build inputs."""
from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

from .jal import JalEngineError, _decode_jal
from .jal_declarations import JalDeclarationError, discover_jal_declarations
from .symbols import SymbolResolverError, load_linker_map, resolve_symbol


class JalRegistrationError(ValueError):
    pass


def generate_jal_registry(overlay_dir: str | Path, *, map_path: str | Path,
                          image_path: str | Path, base_address: int) -> dict[str, Any]:
    if isinstance(base_address, bool) or not isinstance(base_address, int):
        raise JalRegistrationError("base_address must be an integer")
    if not 0 <= base_address <= 0xFFFFFFFF or base_address & 3:
        raise JalRegistrationError("base_address must be an aligned unsigned 32-bit address")
    overlay = Path(overlay_dir)
    if not overlay.is_dir():
        raise JalRegistrationError(f"overlay directory does not exist: {overlay_dir}")
    try:
        image = Path(image_path).read_bytes()
        declarations = discover_jal_declarations(overlay)
        symbols = load_linker_map(map_path)
    except (OSError, JalDeclarationError, SymbolResolverError) as exc:
        raise JalRegistrationError(str(exc)) from exc
    if not image:
        raise JalRegistrationError("overlay image is empty")
    image_end = base_address + len(image)
    if image_end > 0x100000000:
        raise JalRegistrationError("image mapping exceeds the 32-bit address space")

    entries = []
    occupied: list[tuple[int, int, str]] = []
    for declaration in declarations:
        try:
            site = resolve_symbol(symbols, declaration.site_symbol)
            target = resolve_symbol(symbols, declaration.target_symbol)
        except SymbolResolverError as exc:
            raise JalRegistrationError(f"{declaration.declaration_id}: {exc}") from exc
        if not base_address <= site.address < image_end:
            raise JalRegistrationError(
                f"{declaration.declaration_id}: site symbol is outside the supplied image"
            )
        offset = site.address - base_address
        if offset & 3 or offset + 4 > len(image):
            raise JalRegistrationError(
                f"{declaration.declaration_id}: site symbol is unaligned or outside the image"
            )
        word = struct.unpack_from("<I", image, offset)[0]
        if (word >> 26) != 3:
            raise JalRegistrationError(
                f"{declaration.declaration_id}: site symbol does not point to a JAL instruction "
                f"(found 0x{word:08X})"
            )
        try:
            decoded_target = _decode_jal(site.address, word)
        except JalEngineError as exc:
            raise JalRegistrationError(f"{declaration.declaration_id}: {exc}") from exc
        if decoded_target != target.address:
            raise JalRegistrationError(
                f"{declaration.declaration_id}: encoded JAL target "
                f"0x{decoded_target:08X} does not match target symbol "
                f"0x{target.address:08X}"
            )
        entries.append({
            "id": declaration.declaration_id,
            "type": "jal",
            "site_symbol": declaration.site_symbol,
            "file_offset": f"0x{offset:X}",
            "expected_word": f"0x{word:08X}",
            "expected_target": f"0x{decoded_target:08X}",
            "target_symbol": declaration.target_symbol,
        })
        occupied.append((offset, offset + 4, declaration.declaration_id))

    occupied.sort()
    for previous, current in zip(occupied, occupied[1:]):
        if current[0] < previous[1]:
            raise JalRegistrationError(
                f"JAL declaration sites overlap: {previous[2]} and {current[2]}"
            )
    return {"schema_version": 1, "module": overlay.name, "jal": entries}


def write_jal_registry(overlay_dir: str | Path, output_path: str | Path, *,
                       map_path: str | Path, image_path: str | Path,
                       base_address: int) -> dict[str, Any]:
    generated = generate_jal_registry(
        overlay_dir, map_path=map_path, image_path=image_path,
        base_address=base_address,
    )
    destination = Path(output_path)
    hooks: list[dict[str, Any]] = []
    if destination.exists():
        try:
            existing = json.loads(destination.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise JalRegistrationError(f"cannot read existing registry {destination}: {exc}") from exc
        if (not isinstance(existing, dict) or existing.get("schema_version") != 1
                or existing.get("module") != generated["module"]
                or not isinstance(existing.get("hooks"), list)):
            raise JalRegistrationError("existing registry has an incompatible schema or module")
        seen_ids: set[str] = set()
        for index, entry in enumerate(existing["hooks"]):
            if not isinstance(entry, dict) or entry.get("type") not in ("jal", "hook"):
                raise JalRegistrationError(f"existing registry hooks[{index}] is invalid")
            ident = entry.get("id")
            if not isinstance(ident, str) or not ident.strip() or ident in seen_ids:
                raise JalRegistrationError(f"existing registry hooks[{index}] has an invalid or duplicate id")
            seen_ids.add(ident)
            if entry["type"] == "hook":
                hooks.append(entry)
            else:
                hooks.append(entry)
        generated_ids = {entry["id"] for entry in generated["jal"]}
        conflicts = seen_ids & generated_ids
        if conflicts:
            raise JalRegistrationError(
                "generated JAL id conflicts with existing registry id: "
                + ", ".join(sorted(conflicts))
            )
    result = {
        "schema_version": 1,
        "module": generated["module"],
        "hooks": hooks + generated["jal"],
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    try:
        temporary.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        temporary.replace(destination)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise JalRegistrationError(f"cannot write generated registry {destination}: {exc}") from exc
    return result

"""Registry-driven, fail-closed MIPS patch planning and application.

All file/runtime mappings and expected original bytes are explicit. No free
space, load address, symbol offset, or code location is inferred.
"""
from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .hook import HookEngineError, apply_hook_patch, plan_hook_patch
from .jal import JalEngineError, apply_jal_patches, plan_jal_patch
from .symbols import SymbolResolverError, load_linker_map, resolve_symbol


class IntegrationError(ValueError):
    pass


@dataclass(frozen=True)
class IntegrationPlan:
    overlay: str
    image_sha256: str
    base_address: int
    entries: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "overlay": self.overlay,
            "image_sha256": self.image_sha256,
            "base_address": f"0x{self.base_address:08X}",
            "entry_count": len(self.entries),
            "entries": list(self.entries),
        }


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise IntegrationError(f"{field} must be an integer or hexadecimal string")
    try:
        result = int(value, 0) if isinstance(value, str) else int(value)
    except (TypeError, ValueError) as exc:
        raise IntegrationError(f"{field} must be an integer or hexadecimal string") from exc
    if result < 0 or result > 0xFFFFFFFF:
        raise IntegrationError(f"{field} is outside the unsigned 32-bit range")
    return result


def _keys(obj: dict, required: set[str], optional: set[str], context: str) -> None:
    missing = required - obj.keys()
    extra = obj.keys() - required - optional
    if missing or extra:
        details = []
        if missing:
            details.append("missing " + ", ".join(sorted(missing)))
        if extra:
            details.append("unknown " + ", ".join(sorted(extra)))
        raise IntegrationError(f"{context}: " + "; ".join(details))


def _load_registry(path: str | Path, overlay: str) -> list[dict]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IntegrationError(f"cannot read hook registry {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise IntegrationError("hook registry root must be an object")
    if payload.get("schema_version") != 1:
        raise IntegrationError("hook registry schema_version must be 1")
    if payload.get("module") != overlay:
        raise IntegrationError(f"registry module must equal overlay {overlay!r}")
    if not isinstance(payload.get("hooks"), list):
        raise IntegrationError("hook registry 'hooks' must be an array")
    return payload["hooks"]


def build_integration_plan(
    image: bytes, *, base_address: int, overlay: str,
    registry_path: str | Path, map_path: str | Path,
) -> IntegrationPlan:
    """Resolve every registry symbol and validate every patch against one image."""
    if not isinstance(image, bytes):
        image = bytes(image)
    base = _integer(base_address, "base_address")
    if base & 3:
        raise IntegrationError("base_address must be 4-byte aligned")
    if not overlay or not isinstance(overlay, str):
        raise IntegrationError("overlay must be a non-empty string")
    if len(image) and base + len(image) - 1 > 0xFFFFFFFF:
        raise IntegrationError("image mapping exceeds the 32-bit address space")

    entries = _load_registry(registry_path, overlay)
    try:
        symbols = load_linker_map(map_path)
    except SymbolResolverError as exc:
        raise IntegrationError(str(exc)) from exc

    plans: list[tuple[str, Any]] = []
    rendered: list[dict[str, Any]] = []
    ids: set[str] = set()
    occupied: list[tuple[int, int, str]] = []

    for index, item in enumerate(entries):
        context = f"hooks[{index}]"
        if not isinstance(item, dict):
            raise IntegrationError(f"{context} must be an object")
        kind = item.get("type")
        common = {"id", "type", "site_symbol"}
        if kind == "jal":
            required = common | {
                "file_offset", "expected_word", "expected_target", "target_symbol"
            }
            _keys(item, required, set(), context)
        elif kind == "hook":
            required = common | {
                "site_offset", "hook_symbol", "trampoline_offset",
                "expected_words", "expected_trampoline",
            }
            _keys(item, required, set(), context)
        else:
            raise IntegrationError(f"{context}.type must be 'jal' or 'hook'")

        entry_id = item["id"]
        if not isinstance(entry_id, str) or not entry_id.strip():
            raise IntegrationError(f"{context}.id must be a non-empty string")
        if entry_id in ids:
            raise IntegrationError(f"duplicate hook id: {entry_id}")
        ids.add(entry_id)

        try:
            site = resolve_symbol(symbols, item["site_symbol"])
            if kind == "jal":
                offset = _integer(item["file_offset"], f"{context}.file_offset")
                expected_word = _integer(item["expected_word"], f"{context}.expected_word")
                expected_target = _integer(item["expected_target"], f"{context}.expected_target")
                target = resolve_symbol(symbols, item["target_symbol"])
                if base + offset != site.address:
                    raise IntegrationError(
                        f"{entry_id}: base + file_offset does not equal site symbol address"
                    )
                patch = plan_jal_patch(
                    image, offset, base, target.address,
                    expected_word=expected_word, expected_target=expected_target,
                )
                plans.append(("jal", patch))
                occupied.append((offset, offset + 4, entry_id))
                rendered.append({
                    "id": entry_id, "type": "jal",
                    "site_symbol": site.name, "site_address": f"0x{site.address:08X}",
                    "target_symbol": target.name, "target_address": f"0x{target.address:08X}",
                    "patch": patch.to_dict(),
                })
            else:
                site_offset = _integer(item["site_offset"], f"{context}.site_offset")
                trampoline_offset = _integer(
                    item["trampoline_offset"], f"{context}.trampoline_offset"
                )
                hook = resolve_symbol(symbols, item["hook_symbol"])
                if base + site_offset != site.address:
                    raise IntegrationError(
                        f"{entry_id}: base + site_offset does not equal site symbol address"
                    )
                if base + trampoline_offset > 0xFFFFFFFF:
                    raise IntegrationError(f"{entry_id}: trampoline mapping overflows")
                words = item["expected_words"]
                if not isinstance(words, list) or len(words) != 2:
                    raise IntegrationError(f"{entry_id}: expected_words must contain two words")
                expected_words = tuple(
                    _integer(value, f"{context}.expected_words") for value in words
                )
                try:
                    trampoline_guard = bytes.fromhex(item["expected_trampoline"])
                except (TypeError, ValueError) as exc:
                    raise IntegrationError(
                        f"{entry_id}: expected_trampoline must be hexadecimal"
                    ) from exc
                patch = plan_hook_patch(
                    image, site_offset=site_offset, site_pc=site.address,
                    hook_pc=hook.address, trampoline_offset=trampoline_offset,
                    trampoline_pc=base + trampoline_offset,
                    expected_original_words=expected_words,
                    expected_trampoline=trampoline_guard,
                )
                plans.append(("hook", patch))
                occupied.extend([
                    (site_offset, site_offset + 8, entry_id + ":site"),
                    (trampoline_offset, trampoline_offset + 16, entry_id + ":trampoline"),
                ])
                rendered.append({
                    "id": entry_id, "type": "hook",
                    "site_symbol": site.name, "site_address": f"0x{site.address:08X}",
                    "hook_symbol": hook.name, "hook_address": f"0x{hook.address:08X}",
                    "patch": patch.to_dict(),
                })
        except (SymbolResolverError, JalEngineError, HookEngineError) as exc:
            raise IntegrationError(f"{entry_id}: {exc}") from exc

    occupied.sort()
    for previous, current in zip(occupied, occupied[1:]):
        if current[0] < previous[1]:
            raise IntegrationError(
                f"patch regions overlap: {previous[2]} and {current[2]}"
            )

    return IntegrationPlan(
        overlay=overlay,
        image_sha256=hashlib.sha256(image).hexdigest(),
        base_address=base,
        entries=tuple(rendered),
    )


def apply_integration_plan(
    image: bytes, plan: IntegrationPlan, *, base_address: int,
    overlay: str, registry_path: str | Path, map_path: str | Path,
) -> bytes:
    """Rebuild all guards and apply only if the input image matches the plan."""
    current = build_integration_plan(
        image, base_address=base_address, overlay=overlay,
        registry_path=registry_path, map_path=map_path,
    )
    if current != plan:
        raise IntegrationError("integration inputs changed after planning; refusing apply")
    if hashlib.sha256(image).hexdigest() != plan.image_sha256:
        raise IntegrationError("input image hash differs from the planned image")

    # Each engine validates against the original image. Cross-entry overlap was
    # rejected during planning, so applying the immutable plans in order is safe.
    output = image
    for kind, patch in _rebuild_patch_objects(image, plan, base_address, overlay,
                                               registry_path, map_path):
        if kind == "jal":
            output = apply_jal_patches(output, [patch])
        else:
            output = apply_hook_patch(output, patch)
    return output


def _rebuild_patch_objects(image: bytes, plan: IntegrationPlan, base_address: int,
                           overlay: str, registry_path: str | Path,
                           map_path: str | Path) -> list[tuple[str, Any]]:
    """Reconstruct typed plans from the already revalidated registry."""
    from .hook import plan_hook_patch
    from .jal import plan_jal_patch

    symbols = load_linker_map(map_path)
    registry = _load_registry(registry_path, overlay)
    result = []
    for item in registry:
        site = resolve_symbol(symbols, item["site_symbol"]).address
        if item["type"] == "jal":
            target = resolve_symbol(symbols, item["target_symbol"]).address
            result.append(("jal", plan_jal_patch(
                image, _integer(item["file_offset"], "file_offset"), base_address, target,
                expected_word=_integer(item["expected_word"], "expected_word"),
                expected_target=_integer(item["expected_target"], "expected_target"),
            )))
        else:
            hook = resolve_symbol(symbols, item["hook_symbol"]).address
            offset = _integer(item["site_offset"], "site_offset")
            trampoline_offset = _integer(item["trampoline_offset"], "trampoline_offset")
            result.append(("hook", plan_hook_patch(
                image, site_offset=offset, site_pc=site, hook_pc=hook,
                trampoline_offset=trampoline_offset,
                trampoline_pc=base_address + trampoline_offset,
                expected_original_words=tuple(
                    _integer(value, "expected_words") for value in item["expected_words"]
                ),
                expected_trampoline=bytes.fromhex(item["expected_trampoline"]),
            )))
    return result

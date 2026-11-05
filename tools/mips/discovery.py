"""Deterministic inventory of overlay mod sources and hook registry metadata."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from dataclasses import dataclass


class ModDiscoveryError(ValueError):
    pass


@dataclass(frozen=True)
class ModInventory:
    overlay: str
    mod_root: str
    sources: tuple[str, ...]
    headers: tuple[str, ...]
    registry_path: str | None
    registry_hooks: int | None

    def to_dict(self) -> dict:
        return {
            "overlay": self.overlay,
            "mod_root": self.mod_root,
            "source_count": len(self.sources),
            "sources": list(self.sources),
            "header_count": len(self.headers),
            "headers": list(self.headers),
            "registry": {
                "path": self.registry_path,
                "hooks": self.registry_hooks,
            } if self.registry_path is not None else None,
        }


def discover_mod_sources(overlay_dir: str | Path) -> ModInventory:
    """Inventory mod/**/*.c and mod/**/*.h without changing the source tree."""
    overlay = Path(overlay_dir).resolve()
    if not overlay.is_dir():
        raise ModDiscoveryError(f"overlay directory does not exist: {overlay_dir}")
    mod_root = overlay / "mod"
    if not mod_root.is_dir():
        raise ModDiscoveryError(f"overlay has no mod directory: {mod_root}")

    def collect(suffix: str) -> tuple[str, ...]:
        found = []
        for path in mod_root.rglob(f"*{suffix}"):
            if not path.is_file():
                continue
            if path.is_symlink():
                raise ModDiscoveryError(f"symlinked mod source is not allowed: {path}")
            try:
                rel = path.relative_to(overlay).as_posix()
            except ValueError as exc:
                raise ModDiscoveryError(f"mod path escapes overlay: {path}") from exc
            found.append(rel)
        return tuple(sorted(found))

    sources = collect(".c")
    headers = collect(".h")
    registry = mod_root / "hooks.json"
    registry_path = None
    registry_hooks = None
    if registry.exists():
        if registry.is_symlink() or not registry.is_file():
            raise ModDiscoveryError(f"hook registry is not a regular file: {registry}")
        try:
            payload = json.loads(registry.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ModDiscoveryError(f"cannot read hook registry: {exc}") from exc
        if not isinstance(payload, dict):
            raise ModDiscoveryError("hook registry root must be a JSON object")
        if payload.get("schema_version") != 1:
            raise ModDiscoveryError("hook registry schema_version must be 1")
        if payload.get("module") != overlay.name:
            raise ModDiscoveryError(
                f"hook registry module must match overlay directory {overlay.name!r}"
            )
        hooks = payload.get("hooks")
        if not isinstance(hooks, list):
            raise ModDiscoveryError("hook registry 'hooks' must be a JSON array")
        registry_path = registry.relative_to(overlay).as_posix()
        registry_hooks = len(hooks)

    return ModInventory(
        overlay=overlay.name,
        mod_root=mod_root.relative_to(overlay).as_posix(),
        sources=sources,
        headers=headers,
        registry_path=registry_path,
        registry_hooks=registry_hooks,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("overlay", type=Path, help="overlay directory containing mod/")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()
    inventory = discover_mod_sources(args.overlay)
    if args.json:
        print(json.dumps(inventory.to_dict(), indent=2))
    else:
        print(f"Overlay: {inventory.overlay}")
        print(f"C sources: {len(inventory.sources)}")
        for source in inventory.sources:
            print(f"  {source}")
        print(f"Headers: {len(inventory.headers)}")
        for header in inventory.headers:
            print(f"  {header}")
        if inventory.registry_path:
            print(f"Hook registry: {inventory.registry_path} ({inventory.registry_hooks} entries)")
        else:
            print("Hook registry: not present")


if __name__ == "__main__":
    main()

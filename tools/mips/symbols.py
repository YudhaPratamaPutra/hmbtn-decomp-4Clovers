"""Resolve exact linker-map symbol names without guessing addresses.

Supports GNU ld map symbol rows of the form:
    0x80012340                function_name
Input is text from the actual linker's map file; no ELF or source parsing is
performed here. Duplicate names at distinct addresses are reported as
ambiguous and cannot be resolved implicitly.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


_ADDRESS_ROW = re.compile(
    r"^\s*(0x[0-9a-fA-F]{1,8})\s+([A-Za-z_][A-Za-z0-9_.$@]*)"
    r"(?:\s*(?:=|$).*)?$"
)


class SymbolResolverError(ValueError):
    pass


@dataclass(frozen=True, order=True)
class SymbolDefinition:
    name: str
    address: int
    line: int


@dataclass(frozen=True)
class SymbolResolution:
    name: str
    address: int
    definition_lines: tuple[int, ...]

    def to_dict(self) -> dict:
        return {
            "symbol": self.name,
            "address": f"0x{self.address:08X}",
            "definition_lines": list(self.definition_lines),
        }


def parse_linker_map(map_text: str) -> dict[str, tuple[SymbolDefinition, ...]]:
    """Extract address/name rows, preserving duplicate definitions and line numbers."""
    if not isinstance(map_text, str):
        raise SymbolResolverError("linker map content must be text")
    found: dict[str, list[SymbolDefinition]] = {}
    for line_number, line in enumerate(map_text.splitlines(), 1):
        match = _ADDRESS_ROW.match(line)
        if not match:
            continue
        address = int(match.group(1), 16)
        name = match.group(2)
        found.setdefault(name, []).append(
            SymbolDefinition(name=name, address=address, line=line_number)
        )
    return {
        name: tuple(sorted(definitions, key=lambda item: (item.address, item.line)))
        for name, definitions in found.items()
    }


def load_linker_map(path: str | Path) -> dict[str, tuple[SymbolDefinition, ...]]:
    map_path = Path(path)
    try:
        content = map_path.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeError) as exc:
        raise SymbolResolverError(f"cannot read linker map {map_path}: {exc}") from exc
    return parse_linker_map(content)


def resolve_symbol(
    symbols: dict[str, tuple[SymbolDefinition, ...]], name: str
) -> SymbolResolution:
    """Resolve a symbol only if its map definitions agree on one address."""
    if not isinstance(name, str) or not name:
        raise SymbolResolverError("symbol name must be a non-empty string")
    definitions = symbols.get(name)
    if not definitions:
        raise SymbolResolverError(f"symbol not found in linker map: {name}")
    addresses = sorted({item.address for item in definitions})
    if len(addresses) != 1:
        details = ", ".join(f"0x{value:08X}" for value in addresses)
        raise SymbolResolverError(f"ambiguous symbol {name}: definitions at {details}")
    return SymbolResolution(
        name=name,
        address=addresses[0],
        definition_lines=tuple(item.line for item in definitions),
    )


def resolve_symbols(
    symbols: dict[str, tuple[SymbolDefinition, ...]], names: Iterable[str]
) -> list[SymbolResolution]:
    """Resolve a requested list in order; fail the whole request on any missing/ambiguous name."""
    requested = list(names)
    if len(set(requested)) != len(requested):
        raise SymbolResolverError("requested symbol list contains duplicates")
    return [resolve_symbol(symbols, name) for name in requested]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", required=True, type=Path, help="GNU ld program.map")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--symbol", action="append", dest="symbols",
                       help="exact symbol name; may be repeated")
    group.add_argument("--list", action="store_true", help="list extracted symbol names")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    args = parser.parse_args()

    table = load_linker_map(args.map)
    if args.list:
        rows = [
            {"symbol": name, "definitions": [
                {"address": f"0x{item.address:08X}", "line": item.line}
                for item in definitions
            ]}
            for name, definitions in sorted(table.items())
        ]
        print(json.dumps(rows, indent=2) if args.json else
              "\n".join(f"{row['symbol']}: " + ", ".join(
                  item["address"] for item in row["definitions"]
              ) for row in rows))
    else:
        results = resolve_symbols(table, args.symbols)
        print(json.dumps([item.to_dict() for item in results], indent=2) if args.json
              else "\n".join(f"{item.name}=0x{item.address:08X}" for item in results))


if __name__ == "__main__":
    main()

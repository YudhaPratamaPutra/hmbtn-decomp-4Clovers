"""Scan explicit MIPS_AUTO_JAL declarations in overlay mod C sources."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class JalDeclarationError(ValueError):
    pass


_MARKER = "MIPS_AUTO_JAL:"
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True)
class JalDeclaration:
    declaration_id: str
    site_symbol: str
    target_symbol: str
    source: str
    line: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.declaration_id,
            "type": "jal",
            "site_symbol": self.site_symbol,
            "target_symbol": self.target_symbol,
            "source": self.source,
            "line": self.line,
        }


def _comments(source: str) -> list[tuple[int, int, str]]:
    found = []
    i = 0
    while i < len(source):
        if source[i] in ('"', "'"):
            quote = source[i]
            i += 1
            while i < len(source):
                if source[i] == "\\":
                    i += 2
                elif source[i] == quote:
                    i += 1
                    break
                else:
                    i += 1
            continue
        if source.startswith("//", i):
            end = source.find("\n", i)
            end = len(source) if end < 0 else end
            if _MARKER in source[i:end]:
                raise JalDeclarationError("MIPS_AUTO_JAL declarations must use block comments")
            i = end
            continue
        if source.startswith("/*", i):
            end = source.find("*/", i + 2)
            if end < 0:
                raise JalDeclarationError("unterminated block comment")
            end += 2
            comment = source[i:end]
            if _MARKER in comment:
                if not comment[2:-2].lstrip().startswith(_MARKER):
                    raise JalDeclarationError("MIPS_AUTO_JAL marker must begin its block comment")
                found.append((i, end, comment))
            i = end
            continue
        i += 1
    return found


def scan_jal_declarations(source_text: str, *, source_name: str = "<memory>") -> list[JalDeclaration]:
    if not isinstance(source_text, str):
        raise JalDeclarationError("source text must be a string")
    found = []
    ids: set[str] = set()
    sites: set[str] = set()
    for start, _end, comment in _comments(source_text):
        if comment.count(_MARKER) != 1:
            raise JalDeclarationError("each JAL declaration comment must contain exactly one marker")
        payload = comment.split(_MARKER, 1)[1].rsplit("*/", 1)[0].strip()
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise JalDeclarationError(f"invalid JSON in JAL declaration: {exc.msg}") from exc
        if not isinstance(data, dict):
            raise JalDeclarationError("JAL declaration metadata must be a JSON object")
        required = {"id", "type", "site_symbol", "target_symbol"}
        if set(data) != required:
            missing, extra = required - set(data), set(data) - required
            detail = []
            if missing:
                detail.append("missing " + ", ".join(sorted(missing)))
            if extra:
                detail.append("unknown " + ", ".join(sorted(extra)))
            raise JalDeclarationError("JAL declaration: " + "; ".join(detail))
        if data["type"] != "jal":
            raise JalDeclarationError("MIPS_AUTO_JAL type must be 'jal'")
        ident, site, target = data["id"], data["site_symbol"], data["target_symbol"]
        if not isinstance(ident, str) or not ident.strip():
            raise JalDeclarationError("JAL declaration id must be a non-empty string")
        for field, value in (("site_symbol", site), ("target_symbol", target)):
            if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
                raise JalDeclarationError(f"{field} must be a C/linker identifier")
        if ident in ids:
            raise JalDeclarationError(f"duplicate JAL declaration id: {ident}")
        if site in sites:
            raise JalDeclarationError(f"duplicate JAL site declaration: {site}")
        ids.add(ident)
        sites.add(site)
        found.append(JalDeclaration(ident, site, target, source_name,
                                    source_text.count("\n", 0, start) + 1))
    return found


def discover_jal_declarations(overlay_dir: str | Path) -> list[JalDeclaration]:
    overlay = Path(overlay_dir).resolve()
    mod_root = overlay / "mod"
    if not overlay.is_dir():
        raise JalDeclarationError(f"overlay directory does not exist: {overlay_dir}")
    if not mod_root.is_dir():
        raise JalDeclarationError(f"overlay has no mod directory: {mod_root}")
    results = []
    ids: set[str] = set()
    sites: set[str] = set()
    for path in sorted(mod_root.rglob("*.c")):
        if path.is_symlink():
            raise JalDeclarationError(f"symlinked mod source is not allowed: {path}")
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise JalDeclarationError(f"cannot read mod source {path}: {exc}") from exc
        relative = path.relative_to(overlay).as_posix()
        for item in scan_jal_declarations(source, source_name=relative):
            if item.declaration_id in ids:
                raise JalDeclarationError(f"duplicate JAL declaration id across mod sources: {item.declaration_id}")
            if item.site_symbol in sites:
                raise JalDeclarationError(f"duplicate JAL site across mod sources: {item.site_symbol}")
            ids.add(item.declaration_id)
            sites.add(item.site_symbol)
            results.append(item)
    return results

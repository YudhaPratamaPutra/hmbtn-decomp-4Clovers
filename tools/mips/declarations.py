"""Scan explicit MIPS auto-hook declarations embedded in mod C sources.

Declarations are JSON metadata in a block comment immediately before a function
definition. The scanner never infers a game target from a function name.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class HookDeclarationError(ValueError):
    pass


_MARKER = "MIPS_AUTO_HOOK:"
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_FUNCTION_TAIL = re.compile(
    r"([A-Za-z_][A-Za-z0-9_]*)\\s*\\([^;{}]*\\)\\s*$",
    re.DOTALL,
)


@dataclass(frozen=True)
class HookDeclaration:
    declaration_id: str
    hook_symbol: str
    site_symbol: str
    source: str
    line: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.declaration_id,
            "type": "hook",
            "site_symbol": self.site_symbol,
            "hook_symbol": self.hook_symbol,
            "source": self.source,
            "line": self.line,
        }


def _mask_non_code(source: str) -> str:
    """Replace comments and literals with spaces while preserving offsets/newlines."""
    out = list(source)
    i = 0
    n = len(source)
    while i < n:
        if source.startswith("//", i):
            end = source.find("\\n", i)
            end = n if end < 0 else end
            for j in range(i, end):
                out[j] = " "
            i = end
        elif source.startswith("/*", i):
            end = source.find("*/", i + 2)
            if end < 0:
                raise HookDeclarationError("unterminated block comment")
            end += 2
            for j in range(i, end):
                if source[j] != "\\n":
                    out[j] = " "
            i = end
        elif source[i] in ('"', "'"):
            quote = source[i]
            j = i + 1
            while j < n:
                if source[j] == "\\\\":
                    j += 2
                    continue
                if source[j] == quote:
                    j += 1
                    break
                j += 1
            else:
                raise HookDeclarationError("unterminated string or character literal")
            for k in range(i, min(j, n)):
                if source[k] != "\\n":
                    out[k] = " "
            i = j
        else:
            i += 1
    return "".join(out)


def _comment_declarations(source: str) -> list[tuple[int, int, dict[str, Any]]]:
    """Return marker comment spans and parsed JSON metadata."""
    declarations = []
    i = 0
    while i < len(source):
        line = source.find("//", i)
        block = source.find("/*", i)
        candidates = [x for x in (line, block) if x >= 0]
        if not candidates:
            break
        start = min(candidates)
        if start == line:
            end = source.find("\\n", start)
            end = len(source) if end < 0 else end
            comment = source[start:end]
            i = end
        else:
            close = source.find("*/", start + 2)
            if close < 0:
                raise HookDeclarationError("unterminated block comment")
            end = close + 2
            comment = source[start:end]
            i = end
        if _MARKER not in comment:
            continue
        if start == line:
            raise HookDeclarationError("MIPS_AUTO_HOOK declarations must use block comments")
        if comment.count(_MARKER) != 1:
            raise HookDeclarationError("each declaration comment must contain exactly one marker")
        payload = comment.split(_MARKER, 1)[1].rsplit("*/", 1)[0].strip()
        try:
            metadata = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise HookDeclarationError(
                f"invalid JSON in hook declaration at line {source.count(chr(10), 0, start) + 1}: {exc.msg}"
            ) from exc
        if not isinstance(metadata, dict):
            raise HookDeclarationError("hook declaration metadata must be a JSON object")
        declarations.append((start, end, metadata))
    return declarations


def scan_hook_declarations(source_text: str, *, source_name: str = "<memory>") -> list[HookDeclaration]:
    """Find declared hook functions; only explicit marker comments are considered."""
    if not isinstance(source_text, str):
        raise HookDeclarationError("source text must be a string")
    masked = _mask_non_code(source_text)
    comments = _comment_declarations(source_text)
    found: list[HookDeclaration] = []
    seen_ids: set[str] = set()
    seen_sites: set[str] = set()

    for start, end, metadata in comments:
        allowed = {"id", "type", "site_symbol"}
        extra = set(metadata) - allowed
        missing = allowed - set(metadata)
        if missing or extra:
            details = []
            if missing:
                details.append("missing " + ", ".join(sorted(missing)))
            if extra:
                details.append("unknown " + ", ".join(sorted(extra)))
            raise HookDeclarationError("hook declaration: " + "; ".join(details))
        if metadata["type"] != "hook":
            raise HookDeclarationError("MIPS_AUTO_HOOK type must be 'hook'")
        declaration_id = metadata["id"]
        site_symbol = metadata["site_symbol"]
        if not isinstance(declaration_id, str) or not declaration_id.strip():
            raise HookDeclarationError("hook declaration id must be a non-empty string")
        if not isinstance(site_symbol, str) or not _IDENTIFIER.fullmatch(site_symbol):
            raise HookDeclarationError("site_symbol must be a C/linker identifier")
        if declaration_id in seen_ids:
            raise HookDeclarationError(f"duplicate hook declaration id: {declaration_id}")
        if site_symbol in seen_sites:
            raise HookDeclarationError(f"duplicate hook target declaration: {site_symbol}")
        seen_ids.add(declaration_id)
        seen_sites.add(site_symbol)

        tail = masked[end:]
        match = _FUNCTION_TAIL.search(tail)
        if not match:
            line = source_text.count("\\n", 0, start) + 1
            raise HookDeclarationError(
                f"declaration at {source_name}:{line} is not followed by a function definition"
            )
        # A function definition must reach its opening brace before a statement terminator.
        suffix_start = match.end()
        opening = tail.find("{", suffix_start)
        semicolon = tail.find(";", suffix_start)
        if opening < 0 or (semicolon >= 0 and semicolon < opening):
            raise HookDeclarationError("hook declaration is followed by a prototype, not a definition")
        hook_symbol = match.group(1)
        line = source_text.count("\\n", 0, start) + 1
        found.append(HookDeclaration(
            declaration_id, hook_symbol, site_symbol, source_name, line
        ))

    return found


def discover_hook_declarations(overlay_dir: str | Path) -> list[HookDeclaration]:
    """Scan mod/**/*.c deterministically for explicit hook declarations."""
    overlay = Path(overlay_dir).resolve()
    mod_root = overlay / "mod"
    if not overlay.is_dir():
        raise HookDeclarationError(f"overlay directory does not exist: {overlay_dir}")
    if not mod_root.is_dir():
        raise HookDeclarationError(f"overlay has no mod directory: {mod_root}")
    results: list[HookDeclaration] = []
    ids: set[str] = set()
    sites: set[str] = set()
    for path in sorted(mod_root.rglob("*.c")):
        if path.is_symlink():
            raise HookDeclarationError(f"symlinked mod source is not allowed: {path}")
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise HookDeclarationError(f"cannot read mod source {path}: {exc}") from exc
        relative = path.relative_to(overlay).as_posix()
        for declaration in scan_hook_declarations(text, source_name=relative):
            if declaration.declaration_id in ids:
                raise HookDeclarationError(
                    f"duplicate hook declaration id across mod sources: {declaration.declaration_id}"
                )
            if declaration.site_symbol in sites:
                raise HookDeclarationError(
                    f"duplicate hook target across mod sources: {declaration.site_symbol}"
                )
            ids.add(declaration.declaration_id)
            sites.add(declaration.site_symbol)
            results.append(declaration)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overlay", required=True, type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    declarations = discover_hook_declarations(args.overlay)
    payload = [item.to_dict() for item in declarations]
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Hook declarations: {len(payload)}")
        for item in payload:
            print(
                f"  {item['id']}: {item['hook_symbol']} -> "
                f"{item['site_symbol']} ({item['source']}:{item['line']})"
            )


if __name__ == "__main__":
    main()

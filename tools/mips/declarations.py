"""Scan explicit MIPS auto-hook declarations embedded in mod C sources."""
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
    r"([A-Za-z_][A-Za-z0-9_]*)\s*\([^;{}]*\)\s*$", re.DOTALL
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
    """Blank comments and literals while preserving offsets and newlines."""
    out = list(source)
    i = 0
    while i < len(source):
        if source.startswith("//", i):
            end = source.find("\n", i)
            end = len(source) if end < 0 else end
            for j in range(i, end):
                out[j] = " "
            i = end
        elif source.startswith("/*", i):
            end = source.find("*/", i + 2)
            if end < 0:
                raise HookDeclarationError("unterminated block comment")
            end += 2
            for j in range(i, end):
                if source[j] != "\n":
                    out[j] = " "
            i = end
        elif source[i] in ('"', "'"):
            quote = source[i]
            j = i + 1
            while j < len(source):
                if source[j] == "\\":
                    j += 2
                    continue
                if source[j] == quote:
                    j += 1
                    break
                j += 1
            else:
                raise HookDeclarationError("unterminated string or character literal")
            for k in range(i, min(j, len(source))):
                if source[k] != "\n":
                    out[k] = " "
            i = j
        else:
            i += 1
    return "".join(out)


def _comment_declarations(source: str) -> list[tuple[int, int, dict[str, Any]]]:
    """Parse actual C comments, ignoring comment-like text inside literals."""
    declarations = []
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
                raise HookDeclarationError("MIPS_AUTO_HOOK declarations must use block comments")
            i = end
            continue
        if not source.startswith("/*", i):
            i += 1
            continue

        start = i
        close = source.find("*/", start + 2)
        if close < 0:
            raise HookDeclarationError("unterminated block comment")
        end = close + 2
        comment = source[start:end]
        i = end
        if not comment.lstrip().startswith("/*" + _MARKER):
            continue
        if comment.count(_MARKER) != 1:
            raise HookDeclarationError("each declaration comment must contain exactly one marker")
        payload = comment.split(_MARKER, 1)[1].rsplit("*/", 1)[0].strip()
        try:
            metadata = json.loads(payload)
        except json.JSONDecodeError as exc:
            line_number = source.count("\n", 0, start) + 1
            raise HookDeclarationError(
                f"invalid JSON in hook declaration at line {line_number}: {exc.msg}"
            ) from exc
        if not isinstance(metadata, dict):
            raise HookDeclarationError("hook declaration metadata must be a JSON object")
        declarations.append((start, end, metadata))
    return declarations

def scan_hook_declarations(
    source_text: str, *, source_name: str = "<memory>"
) -> list[HookDeclaration]:
    """Find explicitly annotated function definitions; never infer game targets."""
    if not isinstance(source_text, str):
        raise HookDeclarationError("source text must be a string")
    masked = _mask_non_code(source_text)
    found: list[HookDeclaration] = []
    seen_ids: set[str] = set()
    seen_sites: set[str] = set()

    for start, end, metadata in _comment_declarations(source_text):
        allowed = {"id", "type", "site_symbol", "trampoline_offset"}
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
        if trampoline_offset is not None:\n            if isinstance(trampoline_offset, bool):\n                raise HookDeclarationError("trampoline_offset must be a non-negative aligned integer")\n            try:\n                trampoline_offset = int(trampoline_offset, 0) if isinstance(trampoline_offset, str) else int(trampoline_offset)\n            except (TypeError, ValueError) as exc:\n                raise HookDeclarationError("trampoline_offset must be a non-negative aligned integer") from exc\n            if trampoline_offset < 0 or trampoline_offset > 0xFFFFFFFF or trampoline_offset & 3:\n                raise HookDeclarationError("trampoline_offset must be a non-negative aligned integer")\n        if declaration_id in seen_ids:
            raise HookDeclarationError(f"duplicate hook declaration id: {declaration_id}")
        if site_symbol in seen_sites:
            raise HookDeclarationError(f"duplicate hook target declaration: {site_symbol}")
        seen_ids.add(declaration_id)
        seen_sites.add(site_symbol)

        tail = masked[end:]
        brace = tail.find("{")
        semicolon = tail.find(";")
        boundary = min((pos for pos in (brace, semicolon) if pos >= 0), default=-1)
        if boundary < 0 or boundary == semicolon:
            raise HookDeclarationError(
                f"declaration at {source_name}:{source_text.count(chr(10), 0, start) + 1} "
                "is not followed by a function definition"
            )
        signature = tail[:boundary].strip()
        match = _FUNCTION_TAIL.search(signature)
        if not match:
            raise HookDeclarationError(
                f"cannot identify function definition after declaration in {source_name}"
            )
        hook_symbol = match.group(1)
        line_number = source_text.count("\n", 0, start) + 1
        found.append(HookDeclaration(
            declaration_id, hook_symbol, site_symbol, source_name, line_number
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
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise HookDeclarationError(f"cannot read mod source {path}: {exc}") from exc
        relative = path.relative_to(overlay).as_posix()
        for item in scan_hook_declarations(source, source_name=relative):
            if item.declaration_id in ids:
                raise HookDeclarationError(
                    f"duplicate hook declaration id across mod sources: {item.declaration_id}"
                )
            if item.site_symbol in sites:
                raise HookDeclarationError(
                    f"duplicate hook target across mod sources: {item.site_symbol}"
                )
            ids.add(item.declaration_id)
            sites.add(item.site_symbol)
            results.append(item)
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

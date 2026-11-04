#!/usr/bin/env python3
"""Validate and encode Indonesian translations for HMBTN messege0..messege4 BINs.

Single-file mode remains compatible with the previous tool. Batch mode preflights
all five BIN/CSV pairs before writing any translated output files.

Translations stay plain Indonesian in the CSV. Source controls and dynamic inserts are
reconstructed automatically, and translated pages are generated after every four lines.
Writes are staged to a temporary file and atomically replaced only after all selected
records pass validation. Use --output to preserve the original BIN. Use --report-json to export per-record validation results.
"""
from __future__ import annotations
import argparse
import csv
import re
import struct
import sys
import os
import tempfile
import json
import math
import shutil
import hashlib
from pathlib import Path

RECORD_STRIDE = 0x2000
TEXT_OFFSET_IN_RECORD = 0x1800
TEXT_CAPACITY_BYTES = 0x0800
END = 0xFFFF
FACE_PREFIX = (0x0F87, 0x0FF7, 0x0FF4)
PAGE_SEPARATOR = (0x0FFC, 0x0FFB, 0xFFFE, *FACE_PREFIX)
# Unicode characters mapped only where hmbtn-glyph-audit.md identifies the glyph.
# ASCII apostrophe is intentionally omitted: glyph 0x008D is only described as apostrophe-like.
# Glyph IDs with unresolved artwork remain available through explicit <G:XXXX> tokens.
PUNCTUATION = {
    '.': 0x006C,
    ',': 0x008C,
    '?': 0x0062,
    '!': 0x0063,
    '-': 0x0069,
    '(': 0x006A,
    ')': 0x006B,
    ':': 0x0066,
    ';': 0x0067,
    '+': 0x0068,
    '…': 0x0064,
    '○': 0x006D,
    '×': 0x006E,
    '✕': 0x006E,
    '□': 0x0070,
    '△': 0x006F,
    '/': 0x0071,
    '~': 0x0074,
    '&': 0x0076,
    '☆': 0x0077,
    '♥': 0x0080,
    '♡': 0x0081,
    '%': 0x008F,
    '"': 0x0061,  # quote-like glyph confirmed by hmbtn-glyph-audit.md
}
CONTROL_CODES = {
    'FACE': 0x0F87,
    'NO_SCROLL': 0x0FF3,
    'PAGE_BREAK': 0x0FFC,
    'SCROLL_HOLD': 0x0FF1,
    'NO_OP': 0x0FF2,
    'PAGE_END': 0x0FFB,
    'FACE_BANK': 0x0FF7,
    'FACE_SHOW': 0x0FF4,
    'FACE_RELOAD': 0x0FF5,
    'FACE_HIDE': 0x0FF6,
    'CHOICE_2': 0x0FFA,
    'CHOICE_3': 0x0FF9,
    'CHOICE_4': 0x0FF8,
}
TOKEN_RE = re.compile(r'<([^<>]+)>')
CONTROL_TAGS = set(CONTROL_CODES) | {'WAIT:'}


def headers_for(reader):
    headers = reader.fieldnames or []
    # Normalize BOM/encoding artifacts in headers without changing cell contents.
    def normalized(header):
        value = (header or '').strip().lstrip('\ufeff')
        for known in ('Ã¯Â»Â¿', 'ï»¿'):
            while value.startswith(known):
                value = value[len(known):]
        return value
    def find(suffix):
        return next((h for h in headers if normalized(h).endswith(suffix)), None)
    cols = {
        'id': find('record_id_hex'), 'offset': find('file_offset_hex'),
        'source': find('decoded_text'), 'translation': find('indonesian_translation'),
        'status': find('review_status'),
    }
    missing = [k for k, v in cols.items() if v is None and k in ('id', 'offset', 'source', 'translation')]
    if missing:
        raise ValueError(f'CSV missing required columns: {missing}; found {headers!r}')
    return cols


def load_rows(path):
    with path.open('r', encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        c = headers_for(reader)
        rows, seen = [], set()
        for line, row in enumerate(reader, 2):
            try:
                rid = int((row.get(c['id']) or '').strip(), 16)
            except ValueError:
                continue
            if rid in seen:
                raise ValueError(f'CSV line {line}: duplicate record ID 0x{rid:X}')
            seen.add(rid)
            rows.append({
                'line': line, 'id': rid,
                'offset_text': (row.get(c['offset']) or '').strip(),
                'source': row.get(c['source']) or '',
                'translation': row.get(c['translation']) or '',
                'status': (row.get(c['status']) or '').strip() if c['status'] else '',
            })
    return rows


def glyph(ch):
    if 'A' <= ch <= 'Z': return ord(ch) - ord('A')
    if 'a' <= ch <= 'z': return 0x20 + ord(ch) - ord('a')
    if '0' <= ch <= '9': return 0x40 + ord(ch) - ord('0')
    if ch == ' ': return 0x0FFD
    if ch in PUNCTUATION: return PUNCTUATION[ch]
    raise ValueError(f'karakter {ch!r} belum punya pemetaan glyph terverifikasi')


def encode_plain(s):
    out = []
    i = 0
    while i < len(s):
        # The game has a single ellipsis glyph (0x0064).
        if s.startswith('...', i):
            out.append(0x0064)
            i += 3
            continue
        ch = s[i]
        if ch == '\n':
            out.append(0xFFFE)
        else:
            out.append(glyph(ch))
        i += 1
    return out


def validate_line(line, page, line_no):
    if not line.strip():
        raise ValueError(f'halaman {page}, baris {line_no}: baris kosong; gunakan pemisah halaman yang didukung')
    # Spaces at line edges can be intentional layout padding (e.g. aligned names or
    # a space adjacent to a dynamic insert). Preserve them and count them toward the hard limit.
    if len(line) > MAX_DIALOG_LINE_LENGTH:
        raise ValueError(f'halaman {page}, baris {line_no}: {len(line)} karakter; batas keras {MAX_DIALOG_LINE_LENGTH} (target ideal {PREFERRED_DIALOG_LINE_LENGTH})')
    warn_long_dialog_line(len(line), f'halaman {page}, baris {line_no}')


MAX_DIALOG_LINES = 4
PREFERRED_DIALOG_LINE_LENGTH = 30
MAX_DIALOG_LINE_LENGTH = 30


def warn_long_dialog_line(length, context):
    if PREFERRED_DIALOG_LINE_LENGTH < length <= MAX_DIALOG_LINE_LENGTH:
        print(
            f'PERINGATAN: {context} berisi {length} karakter; target ideal '
            f'{PREFERRED_DIALOG_LINE_LENGTH}, batas keras {MAX_DIALOG_LINE_LENGTH}.',
            file=sys.stderr,
        )


def validate_dialog_layout(text, max_lines=MAX_DIALOG_LINES):
    """Validate visible line and page limits without counting markup as text."""
    pages, page_lines = [], []
    line_chars = 0
    pending_newline = False

    def finish_line():
        nonlocal line_chars
        if line_chars:
            page_lines.append(line_chars)
            line_chars = 0

    def finish_page():
        finish_line()
        if page_lines:
            pages.append(list(page_lines))
            page_lines.clear()

    def consume_literal(value):
        nonlocal line_chars, pending_newline
        for ch in value:
            if ch == '\r':
                continue
            if ch == '\n':
                if line_chars:
                    finish_line()
                    pending_newline = True
                elif pending_newline or page_lines:
                    finish_page()
                    pending_newline = False
                continue
            line_chars += 1
            pending_newline = False

    pos = 0
    for match in TOKEN_RE.finditer(text):
        consume_literal(text[pos:match.start()])
        tag = match.group(1)
        if tag == 'NL':
            finish_line()
            pending_newline = False
        elif tag == 'PAGE_BREAK':
            finish_page()
            pending_newline = False
        elif tag == 'PAGE_END':
            pass
        elif tag.startswith('G:') and re.fullmatch(r'G:[0-9A-Fa-f]{4}', tag):
            if not _preserve_source_tag_in_plain_translation(tag):
                line_chars += 1
        # FACE/WAIT/INSERT/CHOICE and other controls are zero-width here.
        # INSERT expansion is runtime-dependent and cannot be measured statically.
        pos = match.end()
    consume_literal(text[pos:])
    finish_page()

    for page_no, lines in enumerate(pages, 1):
        if len(lines) > max_lines:
            raise ValueError(
                f'halaman {page_no}: {len(lines)} baris teks terlihat; batas {max_lines}. '
                'Tambahkan <PAGE_BREAK><PAGE_END> pada batas halaman yang sesuai.'
            )
        for line_no, length in enumerate(lines, 1):
            if length > MAX_DIALOG_LINE_LENGTH:
                raise ValueError(
                    f'halaman {page_no}, baris {line_no}: {length} karakter terlihat; batas keras {MAX_DIALOG_LINE_LENGTH} (target ideal {PREFERRED_DIALOG_LINE_LENGTH})'
                )
            warn_long_dialog_line(length, f'halaman {page_no}, baris {line_no}')


def leading_source_controls(source):
    """Return contiguous recognized control tags at the very start of source text."""
    tags = []
    pos = 0
    while True:
        m = re.match(r'\s*<([^<>]+)>', source[pos:])
        if not m:
            break
        tag = m.group(1)
        if tag not in CONTROL_CODES:
            break
        tags.append(tag)
        pos += m.end()
    return tags


def source_control_tags(source):
    found = []
    for tag in TOKEN_RE.findall(source):
        if tag in CONTROL_CODES or tag.startswith(('CHOICE_', 'INSERT:', 'WAIT:')) or tag in ('PAGE_BREAK', 'PAGE_END', 'NL'):
            found.append(tag)
    return found



def _plain_source_pages(source):
    """Split source markup into page payloads and preserve each boundary's exact control order."""
    tokens = []
    last = 0
    for match in TOKEN_RE.finditer(source):
        if match.start() > last:
            tokens.append(("text", source[last:match.start()]))
        tokens.append(("tag", match.group(1)))
        last = match.end()
    if last < len(source):
        tokens.append(("text", source[last:]))

    pages, boundaries, current = [], [], []
    i = 0
    while i < len(tokens):
        kind, value = tokens[i]
        if kind == "tag" and value in ("PAGE_BREAK", "PAGE_END"):
            boundary = [value]
            i += 1
            while i < len(tokens) and tokens[i][0] == "tag" and tokens[i][1] in ("PAGE_BREAK", "PAGE_END"):
                boundary.append(tokens[i][1])
                i += 1
            pages.append("".join(v if t == "text" else f"<{v}>" for t, v in current).lstrip("\r\n"))
            boundaries.append(boundary)
            current = []
        else:
            current.append(tokens[i])
            i += 1
    # A trailing page delimiter closes the last payload; it does not create a
    # new empty page. Intermediate empty pages are still rejected below.
    if current or not pages:
        pages.append("".join(v if t == "text" else f"<{v}>" for t, v in current).lstrip("\r\n"))

    # A page may intentionally contain only game glyph/control tokens (for example
    # G:007F placeholders or face codes). Do not strip all markup and then mistake
    # that page for an empty page. Reject only pages that contain neither visible
    # text nor any non-boundary token at all. PAGE_BREAK/PAGE_END themselves are
    # delimiters, not page payload.
    def has_page_payload(page):
        if TOKEN_RE.sub("", page).strip():
            return True
        payload_tags = [m.group(1) for m in TOKEN_RE.finditer(page)
                        if m.group(1) not in ("PAGE_BREAK", "PAGE_END")]
        return bool(payload_tags)

    if not pages or any(not has_page_payload(page) for page in pages):
        raise ValueError("struktur halaman sumber berisi halaman yang benar-benar kosong; pemetaan otomatis tidak aman")
    return pages, boundaries


def _plain_visible_lines(value):
    value = TOKEN_RE.sub("", value).replace("\r\n", "\n").replace("\r", "\n")
    return [line for line in value.split("\n") if line.strip()]


def _plain_page_stats(page):
    lines = _plain_visible_lines(page)
    return len("".join(line.strip() for line in lines)), len(lines)


def _plain_page_starts_with_choice(page):
    prefix_match = re.match(r"(?:\s*<[^<>]+>)*", page)
    prefix = prefix_match.group(0) if prefix_match else ""
    return any(tag.startswith("CHOICE_") for tag in TOKEN_RE.findall(prefix))


def is_purchase_quantity_help(source):
    """Identify non-scrolling button help that controls a purchase quantity panel."""
    return bool(
        re.search(r"<NO_SCROLL>", source, re.IGNORECASE)
        and re.search(
            r"D\s*button\s*:\s*(?:Move\s*/\s*)?Change\s+Quantity",
            source,
            re.IGNORECASE,
        )
    )


def validate_purchase_quantity_help(text):
    """The quantity overlay covers later pages: its button help must stay on one page."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    # Both explicit page controls and a blank-line page separator count as a new page.
    if re.search(r"<PAGE_BREAK>|(?:\n[ \t]*\n)", normalized):
        raise ValueError(
            "petunjuk tombol arah untuk jumlah pembelian tidak boleh membuat halaman baru; "
            "ringkas terjemahan agar muat dalam satu halaman"
        )
    visible = TOKEN_RE.sub("", normalized)
    lines = visible.split("\n")
    if len(lines) > MAX_DIALOG_LINES:
        raise ValueError(
            f"petunjuk jumlah pembelian memiliki {len(lines)} baris; "
            f"maksimal {MAX_DIALOG_LINES} baris agar tidak tertimpa panel jumlah"
        )
    for line_no, line in enumerate(lines, 1):
        if len(line) > MAX_DIALOG_LINE_LENGTH:
            raise ValueError(
                f"petunjuk jumlah pembelian baris {line_no} memiliki {len(line)} karakter; "
                f"maksimal {MAX_DIALOG_LINE_LENGTH}"
            )


def _plain_source_line_layout(page):
    """Map physical source lines to visible target slots and identify INSERT-only rows."""
    physical_lines = page.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    active_flags = []
    insert_only_slots = []
    for line in physical_lines:
        visible = TOKEN_RE.sub("", line).strip()
        tags = TOKEN_RE.findall(line)
        has_insert = any(tag.startswith("INSERT:") for tag in tags)
        has_special_glyph = any(
            tag.startswith("G:") and re.fullmatch(r"G:[0-9A-Fa-f]{4}", tag)
            and not _is_mapped_visible_glyph_code(int(tag[2:], 16))
            and not 0x0E38 <= int(tag[2:], 16) <= 0x0FEF
            for tag in tags
        )
        active = bool(visible) or has_insert or has_special_glyph
        if active and has_insert and not visible:
            insert_only_slots.append(sum(active_flags))
        active_flags.append(active)

    active_count = sum(active_flags)
    line_map = []
    seen = 0
    for active in active_flags:
        if active:
            line_map.append(seen)
            seen += 1
        else:
            line_map.append(min(seen, max(0, active_count - 1)))
    return line_map, active_count, insert_only_slots


def _plain_target_lines(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    raw = text.split("\n")
    lines, blank_boundaries = [], []
    for line in raw:
        if not line.strip():
            if lines:
                blank_boundaries.append(len(lines))
        else:
            lines.append(line)
    return lines, blank_boundaries


def _plain_segment_pages(source_pages, target_lines, blank_boundaries):
    """Infer target line groups from source page lengths, source line counts, and punctuation."""
    n, m = len(source_pages), len(target_lines)
    if n == 1:
        return [(0, m)]
    stats = [_plain_page_stats(page) for page in source_pages]
    dp = {(0, 0): (0.0, [])}
    line_penalty = 0.25
    blank_bonus = 0.40
    punctuation_penalty = 0.60
    for page_no in range(1, n + 1):
        source_chars, source_line_count = stats[page_no - 1]
        source_visible = TOKEN_RE.sub("", source_pages[page_no - 1]).strip()
        source_end = source_visible[-1] if source_visible else ""
        for end in range(page_no, m - (n - page_no) + 1):
            best = None
            for start in range(page_no - 1, end):
                previous = dp.get((page_no - 1, start))
                if previous is None:
                    continue
                previous_score, previous_path = previous
                group = target_lines[start:end]
                target_chars = sum(len(line.strip()) for line in group)
                score = abs(math.log((target_chars + 1) / (source_chars + 1)))
                score += line_penalty * abs((end - start) - source_line_count)
                target_end = group[-1].rstrip()[-1:] if group[-1].rstrip() else ""
                source_terminal = source_end in ".!?"
                target_terminal = target_end in ".!?"
                if source_terminal != target_terminal:
                    score += punctuation_penalty
                elif source_terminal and target_terminal and source_end != target_end:
                    score += 0.10
                if page_no < n and end in blank_boundaries:
                    score -= blank_bonus
                candidate = (previous_score + score, previous_path + [(start, end)])
                if best is None or candidate[0] < best[0]:
                    best = candidate
            if best is not None:
                dp[(page_no, end)] = best
    result = dp.get((n, m))
    if result is None:
        raise ValueError("baris terjemahan tidak cukup untuk memetakan semua halaman sumber")
    return result[1]

def _plain_insert_code(tag):
    if not re.fullmatch(r"INSERT:4[0-9A-Fa-f]{3}", tag):
        raise ValueError(f"sisipan sumber <{tag}> tidak dikenali")
    return int(tag[7:], 16)


def _plain_control_code(tag):
    if tag in CONTROL_CODES:
        return CONTROL_CODES[tag]
    if re.fullmatch(r"G:[0-9A-Fa-f]{4}", tag):
        return int(tag[2:], 16)
    if re.fullmatch(r"WAIT:[0-9]+", tag):
        frames = int(tag.split(":", 1)[1])
        if not 0 <= frames <= 10:
            raise ValueError(f"<{tag}> di luar rentang WAIT yang diketahui (0..10 frame)")
        return 0x0E2F - frames
    if tag == "NL":
        return 0xFFFE
    if tag.startswith("INSERT:"):
        return _plain_insert_code(tag)
    if tag == "END":
        raise ValueError("jangan tulis <END>; konverter menambahkan 0xFFFF otomatis")
    raise ValueError(f"tag sumber <{tag}> tidak didukung; pemetaan otomatis tidak aman")


def _plain_insert_position(lines, line_index, tag, source_page, token_start, used_positions):
    """Map INSERT to its source-context line, not to a global CSV punctuation gap.

    English source order is a positional hint. Indonesian word order can differ,
    so punctuation and word boundaries are considered only on the mapped target line.
    """
    source_before = TOKEN_RE.sub("", source_page[:token_start])
    source_after = TOKEN_RE.sub("", source_page[token_start:])
    source_before = source_before.replace("\r\n", "\n").replace("\r", "\n")
    source_after = source_after.replace("\r\n", "\n").replace("\r", "\n")
    source_prefix = source_before.split("\n")[-1].rstrip()
    source_suffix = source_after.split("\n", 1)[0].lstrip()

    if not 0 <= line_index < len(lines):
        raise ValueError(f"posisi <{tag}> tidak memiliki baris konteks terjemahan")

    line = lines[line_index]
    pos = None
    # If the mapped target line starts with punctuation, the translated sentence
    # has wrapped the punctuation onto the next line. Keep the dynamic value with
    # the preceding translated words instead of starting a new line with the value.
    if source_prefix and line_index > 0 and line.lstrip()[:1] in ".,!?;:":
        previous_index = line_index - 1
        previous_pos = len(lines[previous_index].rstrip())
        if (previous_index, previous_pos) not in used_positions:
            line_index = previous_index
            line = lines[line_index]
            pos = previous_pos

    if pos is None and not source_suffix:
        pos = len(line.rstrip())
    elif pos is None and not source_prefix:
        pos = len(line) - len(line.lstrip())
    elif pos is None:
        source_prefix_words = len(re.findall(r"\w+", source_prefix))
        source_suffix_words = len(re.findall(r"\w+", source_suffix))
        source_word_total = source_prefix_words + source_suffix_words
        if source_word_total:
            fraction = source_prefix_words / source_word_total
            target_boundaries = [0] + [match.end() for match in re.finditer(r"\S+", line)]
            target_word_slot = round(fraction * (len(target_boundaries) - 1))
            estimate = target_boundaries[min(target_word_slot, len(target_boundaries) - 1)]
        else:
            fraction = len(source_prefix) / max(1, len(source_prefix) + len(source_suffix))
            estimate = round(fraction * len(line))
        punctuation = []
        source_punctuation = source_suffix[:1] if source_suffix[:1] in ".,!?;:" else ""
        if source_punctuation:
            matching = []
            for index, char in enumerate(line):
                if char == source_punctuation:
                    candidate = index - 1 if index > 0 and line[index - 1].isspace() else index
                    if (line_index, candidate) not in used_positions:
                        matching.append(candidate)
            if matching:
                pos = min(matching, key=lambda candidate: abs(candidate - estimate))
        if pos is None:
            for index, char in enumerate(line):
                if char in ".,!?;:" and (index == 0 or line[index - 1].isspace()):
                    candidate = index - 1 if index > 0 and line[index - 1].isspace() else index
                    if (line_index, candidate) not in used_positions:
                        punctuation.append(candidate)
            if punctuation:
                pos = min(punctuation, key=lambda candidate: abs(candidate - estimate))
        if pos is None:
            boundaries = [0]
            for index, char in enumerate(line):
                if char.isspace():
                    boundaries.append(index + 1)
            boundaries.append(len(line))
            available = [candidate for candidate in boundaries
                         if (line_index, candidate) not in used_positions]
            if not available:
                raise ValueError(f"posisi <{tag}> bertabrakan dengan INSERT lain pada baris {line_index + 1}")
            pos = min(available, key=lambda candidate: abs(candidate - estimate))

    previous_tokens = list(TOKEN_RE.finditer(source_page[:token_start]))
    previous_insert = next(
        (match for match in reversed(previous_tokens)
         if match.group(1).startswith("INSERT:")),
        None,
    )
    adjacent_insert = False
    if previous_insert is not None:
        between = source_page[previous_insert.end():token_start]
        between_tags = TOKEN_RE.findall(between)
        between_visible = TOKEN_RE.sub("", between)
        # Repeated dynamic values may be separated by retained special-glyph
        # tags (e.g. <G:007F>). Keep these events at the same source slot and
        # preserve their order. A line break or visible text means a new slot.
        adjacent_insert = (
            "\n" not in between
            and "\r" not in between
            and not between_visible.strip()
            and all(tag.startswith("G:") for tag in between_tags)
        )
    if adjacent_insert:
        prior_positions = [candidate for used_line, candidate in used_positions
                           if used_line == line_index]
        if prior_positions:
            pos = min(prior_positions, key=lambda candidate: abs(candidate - pos))
    if (line_index, pos) in used_positions and not adjacent_insert:
        raise ValueError(f"posisi <{tag}> bertabrakan dengan INSERT lain pada baris {line_index + 1}")
    used_positions.add((line_index, pos))
    return line_index, pos



def _is_mapped_visible_glyph_code(code):
    """True when <G:XXXX> denotes a text glyph that translated text can spell itself.

    Plain translations supply their own letters and punctuation. Re-inserting such a
    source glyph would duplicate punctuation (notably G:008C, comma). Face codes and
    unresolved special symbols remain source-derived events.
    """
    if 0x0000 <= code <= 0x0019 or 0x0020 <= code <= 0x0039 or 0x0040 <= code <= 0x0049:
        return True
    if code == 0x0FFD or code in set(PUNCTUATION.values()) or code in (0x0050, 0x0051, 0x0054, 0x0055):
        return True
    return False


def _preserve_source_tag_in_plain_translation(tag):
    """Return whether a source tag is structural or an unresolved glyph needing retention."""
    if not tag.startswith('G:'):
        return True
    if not re.fullmatch(r'G:[0-9A-Fa-f]{4}', tag):
        return True
    code = int(tag[2:], 16)
    if _is_mapped_visible_glyph_code(code):
        return False
    # The audited 0xE38..0xFEF range is face data, not text punctuation.
    # Unresolved G glyphs are retained rather than silently discarded.
    return True


def encode_plain_source(text, rid, source):
    """Encode plain Indonesian while rebuilding source controls from decoded_text."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    if not normalized.strip():
        raise ValueError("kolom terjemahan kosong")
    source_pages, boundaries = _plain_source_pages(source)
    target_lines, blank_boundaries = _plain_target_lines(normalized)
    if not target_lines:
        raise ValueError("kolom terjemahan tidak memiliki baris teks")
    # Dynamic-insert pages carry distinct UI/layout contexts. Never merge them:
    # doing so can move separate values (farm name, menu choices) onto one line.
    preserve_insert_page_boundaries = (
        len(source_pages) > 1
        and all(re.search(r"<INSERT:4[0-9A-Fa-f]{3}>", page) for page in source_pages)
    )
    # Ordinary prose pages may be consolidated, but CHOICE and repeated-INSERT
    # pages must retain their semantic boundaries.
    if len(source_pages) > len(target_lines):
        choice_pages = [
            index for index, page in enumerate(source_pages)
            if index > 0 and _plain_page_starts_with_choice(page)
        ]
        if choice_pages:
            consolidated = []
            pending = []
            for index, page in enumerate(source_pages):
                if index in choice_pages:
                    if pending:
                        consolidated.append("\n".join(item.strip("\r\n") for item in pending))
                        pending = []
                    consolidated.append(page)
                else:
                    pending.append(page)
            if pending:
                consolidated.append("\n".join(item.strip("\r\n") for item in pending))
            source_pages = consolidated
            if len(source_pages) > len(target_lines):
                raise ValueError(
                    "baris terjemahan tidak cukup untuk mempertahankan halaman pilihan "
                    "CHOICE secara terpisah; tambahkan baris terjemahan yang sesuai"
                )
        elif preserve_insert_page_boundaries:
            raise ValueError(
                "halaman sumber dengan INSERT berulang tidak boleh digabung; "
                "tambahkan baris terjemahan untuk mempertahankan setiap halaman"
            )
        else:
            source_pages = ["\n".join(page.strip("\r\n") for page in source_pages)]
    # A leading blank line can represent a source line containing only a dynamic
    # insert (for example, a name on its own line). Preserve it only when the source
    # actually begins with an INSERT before its first visible text.
    leading_blank_lines = len(normalized) - len(normalized.lstrip("\n"))
    source_first_page = source_pages[0]
    source_prefix_match = re.match(r"(?:\s*<[^<>]+>)*", source_first_page)
    source_prefix = source_prefix_match.group(0) if source_prefix_match else ""
    has_leading_insert = bool(re.search(r"<INSERT:4[0-9A-Fa-f]{3}>", source_prefix))
    for line_no, line in enumerate(target_lines, 1):
        if len(line) > MAX_DIALOG_LINE_LENGTH:
            raise ValueError(f"baris {line_no}: {len(line)} karakter; batas keras {MAX_DIALOG_LINE_LENGTH} (target ideal {PREFERRED_DIALOG_LINE_LENGTH})")
        warn_long_dialog_line(len(line), f'baris terjemahan {line_no}')
    if any(not line.strip() for line in target_lines):
        raise ValueError("baris terjemahan kosong tidak didukung sebagai teks")

    # Source page boundaries describe the English layout, not a hard limit for
    # Indonesian. Keep source-page alignment only for locating source controls;
    # the translated output is paginated independently in groups of four lines.
    groups = _plain_segment_pages(source_pages, target_lines, blank_boundaries)
    leading_slots = min(leading_blank_lines, 2) if has_leading_insert else 0
    if leading_slots:
        target_lines = target_lines[:groups[0][0]] + ([""] * leading_slots) + target_lines[groups[0][0]:]
        groups = [
            (start if i == 0 else start + leading_slots,
             end + leading_slots)
            for i, (start, end) in enumerate(groups)
        ]
    # Expand choice rows that contain only dynamic INSERT values. Their text comes
    # from runtime data, so the CSV should not need dummy Indonesian words for them.
    prepared_page_lines = []
    for page_index, (start, end) in enumerate(groups):
        page = source_pages[page_index]
        page_lines = list(target_lines[start:end])
        _, source_slot_count, insert_only_slots = _plain_source_line_layout(page)
        if _plain_page_starts_with_choice(page) and insert_only_slots:
            text_slots = [slot for slot in range(source_slot_count) if slot not in insert_only_slots]
            if len(page_lines) != len(text_slots):
                raise ValueError(
                    f"halaman pilihan memerlukan {len(text_slots)} baris teks selain INSERT, "
                    f"tetapi terjemahan menyediakan {len(page_lines)}"
                )
            expanded = [""] * source_slot_count
            for slot, line in zip(text_slots, page_lines):
                expanded[slot] = line
            page_lines = expanded
        prepared_page_lines.append(page_lines)

    total_target_lines = sum(len(lines) for lines in prepared_page_lines)
    emitted_lines = 0
    lines_on_current_page = 0
    words = []
    for page_index, (start, end) in enumerate(groups):
        page = source_pages[page_index]
        page_lines = prepared_page_lines[page_index]
        if (page_index > 0
                and (_plain_page_starts_with_choice(page) or preserve_insert_page_boundaries)
                and emitted_lines and lines_on_current_page):
            words.extend((CONTROL_CODES["PAGE_BREAK"], CONTROL_CODES["PAGE_END"]))
            lines_on_current_page = 0
        if not page_lines:
            raise ValueError(f"halaman {page_index + 1} tidak memiliki baris terjemahan")
        _, _, insert_only_slots = _plain_source_line_layout(page)
        allowed_blank_slots = set(insert_only_slots)
        if page_index == 0 and has_leading_insert and leading_slots:
            allowed_blank_slots.update(range(min(leading_slots, len(page_lines))))
        if any(not line.strip() and idx not in allowed_blank_slots
               for idx, line in enumerate(page_lines)):
            raise ValueError(
                "baris terjemahan kosong hanya diizinkan untuk baris INSERT dinamis otomatis"
            )

        # Events are (target line index, character position, source order, glyph/control halfword).
        events = []
        prefix_seen_text = False
        source_order = 0
        used_insert_positions = set()
        token_matches = list(TOKEN_RE.finditer(page))
        visible_before_all = ""
        for match in token_matches:
            tag = match.group(1)
            if not _preserve_source_tag_in_plain_translation(tag):
                continue
            before = TOKEN_RE.sub("", page[:match.start()])
            after = TOKEN_RE.sub("", page[match.end():])
            before_stripped = before.strip()
            at_prefix = not before_stripped
            source_line_map, source_line_count, _ = _plain_source_line_layout(page)
            physical_source_line_index = before.replace("\r\n", "\n").replace("\r", "\n").count("\n")
            source_line_index = source_line_map[
                min(physical_source_line_index, len(source_line_map) - 1)
            ]
            after_text_on_line = bool(before.split("\n")[-1].strip())
            if page_index == 0 and leading_slots:
                target_line_index = source_line_index
            else:
                raw_target_line_index = (
                    source_line_index * max(0, len(page_lines) - 1)
                    / max(1, source_line_count - 1)
                )
                target_line_index = int(math.floor(raw_target_line_index + 0.5))
            target_line_index = max(0, min(len(page_lines) - 1, target_line_index))

            if tag in ("PAGE_BREAK", "PAGE_END"):
                continue
            if tag.startswith("INSERT:"):
                # Map inserts at a source physical line start to the translated line start.
                if not before.split("\n")[-1].strip():
                    li, pos = target_line_index, 0
                    source_suffix = TOKEN_RE.sub("", page[match.end():]).split("\n", 1)[0].lstrip()
                    target_line = page_lines[li]
                    # In Indonesian map labels, "Peternakan [farm name]" is the
                    # natural reverse order of the English "[farm name] Farm".
                    if (source_suffix.lower().startswith("farm")
                            and target_line.strip().lower() == "peternakan"):
                        pos = len(target_line)
                    if (li, pos) in used_insert_positions:
                        li, pos = _plain_insert_position(page_lines, target_line_index, tag, page, match.start(), used_insert_positions)
                    else:
                        used_insert_positions.add((li, pos))
                else:
                    li, pos = _plain_insert_position(page_lines, target_line_index, tag, page, match.start(), used_insert_positions)
                events.append((li, pos, source_order, _plain_insert_code(tag)))
            else:
                code = _plain_control_code(tag)
                pos = len(page_lines[target_line_index]) if after_text_on_line and not at_prefix else 0
                if at_prefix:
                    pos = 0
                events.append((target_line_index, pos, source_order, code))
            source_order += 1

        # A control immediately before an INSERT can otherwise be placed after the
        # translated punctuation placeholder. Keep all source-derived events in source
        # order by moving an earlier event back to the next event's inferred position
        # whenever their inferred target positions would reverse.
        events.sort(key=lambda event: event[2])
        for event_index in range(len(events) - 2, -1, -1):
            current = events[event_index]
            following = events[event_index + 1]
            if (current[0], current[1]) > (following[0], following[1]):
                events[event_index] = (following[0], following[1], current[2], current[3])

        # Encode each line, inserting source-derived controls at inferred positions.
        for line_index, line in enumerate(page_lines):
            line_events = sorted((e for e in events if e[0] == line_index), key=lambda e: (e[1], e[2]))
            cursor = 0
            for _, pos, _, code in line_events:
                pos = max(cursor, min(len(line), pos))
                words.extend(encode_plain(line[cursor:pos]))
                words.append(code)
                cursor = pos
            words.extend(encode_plain(line[cursor:]))
            emitted_lines += 1
            lines_on_current_page += 1
            if emitted_lines < total_target_lines:
                if lines_on_current_page == MAX_DIALOG_LINES:
                    # A translated page ends after exactly four visible lines.
                    # Semantic choice pages restart this counter at their boundary.
                    words.append(CONTROL_CODES["PAGE_BREAK"])
                    words.append(CONTROL_CODES["PAGE_END"])
                    lines_on_current_page = 0
                else:
                    words.append(0xFFFE)
        # PAGE_BREAK/PAGE_END from decoded_text are intentionally not replayed:
        # translated pagination is derived from the Indonesian line count above.
    words.append(END)
    return words


def encode_text(text, rid, source='', message_index=None):
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    if not text.strip():
        raise ValueError('kolom terjemahan kosong')

    # Quantity controls share the screen with a purchase-unit overlay. Unlike normal
    # dialogue, this specific NO_SCROLL help must never paginate under that overlay.
    if is_purchase_quantity_help(source):
        validate_purchase_quantity_help(text)

    # The known intro record retains its tested two-page format and original face/page controls.
    if message_index == 3 and rid == 0x3A2 and not TOKEN_RE.search(text):
        text = text.strip('\n')
        pages = re.split(r'\n[ \t]*\n+', text)
        if len(pages) != 2:
            raise ValueError('record 0x3A2 harus memiliki tepat 2 halaman, dipisahkan satu baris kosong')
        if not all(p.strip() for p in pages):
            raise ValueError('halaman kosong tidak diizinkan')
        words = list(FACE_PREFIX)
        for pno, page in enumerate(pages):
            if pno:
                words.extend(PAGE_SEPARATOR)
            for lno, line in enumerate(page.split('\n'), 1):
                validate_line(line, pno + 1, lno)
                if lno > 1: words.append(0xFFFE)
                words.extend(glyph(ch) for ch in line)
        words.append(END)
        return words

    # Plain translation cells contain no markup: reconstruct source controls from decoded_text.
    # Tagged translations keep the original v4 validation path for regression compatibility.
    if not TOKEN_RE.search(text):
        return encode_plain_source(text, rid, source)

    text = text.strip('\n')

    # Preserve a small set of audited non-leading source controls automatically.
    # Trailing INSERT controls stay at the end of the translated sentence.
    # PAGE_BREAK/PAGE_END sequences are placed at the blank-line page boundary;
    # the translation must provide enough blank-line boundaries for the controls.
    leading = leading_source_controls(source)
    src_tags = source_control_tags(source)
    nonleading = [tag for tag in src_tags if tag not in leading]
    explicit_before = TOKEN_RE.findall(text)

    trailing_inserts = []
    source_tokens = list(TOKEN_RE.finditer(source))
    if source_tokens:
        last_insert = next((m for m in reversed(source_tokens)
                            if m.group(1).startswith('INSERT:')), None)
        if last_insert and not source[last_insert.end():].strip(' \t\r\n.,!?…'):
            trailing_inserts = [m.group(1) for m in source_tokens
                                if m.group(1).startswith('INSERT:')]

    if trailing_inserts:
        for tag in trailing_inserts:
            if tag not in explicit_before:
                text = text.rstrip() + f'<{tag}>'
                explicit_before.append(tag)

    page_tags = [tag for tag in nonleading if tag in ('PAGE_BREAK', 'PAGE_END')]
    other_nonleading = [tag for tag in nonleading if tag not in ('PAGE_BREAK', 'PAGE_END') and not tag.startswith('INSERT:')]
    if page_tags and not other_nonleading and not any(tag in explicit_before for tag in page_tags):
        # Auto-place only the one audited page boundary: PAGE_BREAK + PAGE_END.
        # Multiple page boundaries must be explicit so controls are not collapsed
        # onto the first blank line by accident.
        if page_tags != ['PAGE_BREAK', 'PAGE_END']:
            raise ValueError('urutan kontrol halaman memiliki lebih dari satu batas; tempatkan kontrol halaman secara eksplisit')
        boundary = re.search(r'\n[ \t]*\n', text)
        if boundary:
            markup = ''.join(f'<{tag}>' for tag in page_tags)
            text = text[:boundary.start()] + '\n' + markup + text[boundary.start():]
            explicit_before = TOKEN_RE.findall(text)
        else:
            raise ValueError('teks terjemahan perlu satu baris kosong pada posisi pergantian halaman untuk mempertahankan kontrol halaman sumber')

    # Keep translation cells readable: leading source controls are automatically copied.
    explicit_tags = TOKEN_RE.findall(text)
    # Validate the complete ordered structural-control sequence, not just counts.
    # Leading source controls are copied automatically, and any audited auto-insert
    # (single page boundary / trailing dynamic insert) is already present in text by
    # this point. G:XXXX glyphs are not structural controls and are filtered out.
    expected_controls = list(src_tags)
    if leading:
        if expected_controls[:len(leading)] != leading:
            raise ValueError('kontrol awal hasil ekstraksi tidak sejajar dengan urutan tag sumber')
        expected_controls = expected_controls[len(leading):]
    actual_controls = [tag for tag in explicit_tags
                       if tag in CONTROL_CODES or tag.startswith(('INSERT:', 'WAIT:')) or tag == 'NL']
    if ([tag for tag in expected_controls if tag not in ('PAGE_BREAK', 'PAGE_END')] != [tag for tag in actual_controls if tag not in ('PAGE_BREAK', 'PAGE_END')] or actual_controls.count('PAGE_BREAK') < expected_controls.count('PAGE_BREAK') or actual_controls.count('PAGE_END') < expected_controls.count('PAGE_END')):
        mismatch_index = next((i for i, (a, b) in enumerate(zip(expected_controls, actual_controls)) if a != b),
                              min(len(expected_controls), len(actual_controls)))
        expected_at = expected_controls[mismatch_index] if mismatch_index < len(expected_controls) else '<akhir>'
        actual_at = actual_controls[mismatch_index] if mismatch_index < len(actual_controls) else '<akhir>'
        raise ValueError(
            'urutan kode kontrol berbeda dari sumber pada posisi '
            f'{mismatch_index + 1}: sumber={expected_at}, terjemahan={actual_at}; '
            f'jumlah sumber={len(expected_controls)}, terjemahan={len(actual_controls)}'
        )
    words = []
    if explicit_tags and leading:
        explicit_leading = explicit_tags[:len(leading)]
        if explicit_leading == leading:
            raise ValueError('tag kontrol awal sudah ditambahkan manual; hapus tag dari terjemahan karena konverter menyalinnya otomatis')
    words.extend(CONTROL_CODES[t] for t in leading)

    # Controls elsewhere in the source affect behavior/order. Require explicit placement
    # for non-leading controls rather than silently relocating them into the translation.
    for tag in src_tags:
        if tag in leading:
            continue
        if tag in ('PAGE_BREAK', 'PAGE_END') and message_index == 3 and rid == 0x3A2:
            continue
        if tag not in explicit_tags:
            raise ValueError(f'kode kontrol sumber <{tag}> tidak dapat ditempatkan otomatis; posisi harus diaudit sebelum record ini aman diterjemahkan')

    pos = 0
    for m in TOKEN_RE.finditer(text):
        words.extend(encode_plain(text[pos:m.start()]))
        token = m.group(1)
        if token in CONTROL_CODES:
            words.append(CONTROL_CODES[token])
        elif re.fullmatch(r'G:[0-9A-Fa-f]{4}', token):
            words.append(int(token[2:], 16))
        elif re.fullmatch(r'INSERT:4[0-9A-Fa-f]{3}', token):
            words.append(int(token[7:], 16))
        elif re.fullmatch(r'WAIT:[0-9]+', token):
            frames = int(token.split(':', 1)[1])
            # Source: 0xE25..0xE2F represent 10..0 frames respectively.
            if not 0 <= frames <= 10:
                raise ValueError(f'<{token}> di luar rentang WAIT yang diketahui (0..10 frame)')
            words.append(0x0E2F - frames)
        elif token == 'NL':
            words.append(0xFFFE)
        elif token == 'END':
            raise ValueError('jangan tulis <END>; konverter menambahkan 0xFFFF otomatis')
        else:
            raise ValueError(f'tag <{token}> tidak didukung atau ambigu; jangan menebak kode kontrol')
        pos = m.end()
    words.extend(encode_plain(text[pos:]))
    if not words:
        raise ValueError('tidak ada teks yang dapat dikonversi')

    # Enforce visible layout limits for tagged translations as well.
    validate_dialog_layout(text)
    words.append(END)
    return words


def get_original(data, rid, expected_offset):
    calc = rid * RECORD_STRIDE + TEXT_OFFSET_IN_RECORD
    if expected_offset != calc:
        raise ValueError(f'offset CSV 0x{expected_offset:X} tidak cocok dengan hitungan record 0x{calc:X}')
    if calc + TEXT_CAPACITY_BYTES > len(data):
        raise ValueError('area teks record berada di luar ukuran file BIN')
    region = data[calc:calc + TEXT_CAPACITY_BYTES]
    words = struct.unpack('<' + 'H' * (len(region) // 2), region)
    try: end = words.index(END)
    except ValueError: raise ValueError('record asli tidak memiliki penanda 0xFFFF di area teks')
    return calc, list(words[:end + 1])


def process(binary_path, csv_path, only_id=None, check_only=False, output_path=None,
            report_path=None, message_index=None, quiet=False):
    if message_index is None:
        message_index = detect_message_index(binary_path)
    rows = load_rows(csv_path)
    chosen = [r for r in rows if r['translation'].strip() and (only_id is None or r['id'] == only_id)]
    if only_id is not None and not chosen:
        raise ValueError(f'tidak ada terjemahan untuk record 0x{only_id:X} di CSV')
    if not chosen:
        empty_report = {
            'csv': str(csv_path), 'bin': str(binary_path),
            'message_index': message_index, 'selected_records': 0,
            'valid_records': 0, 'error_records': 0, 'check_only': check_only,
            'records': []
        }
        if report_path:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(empty_report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            if not quiet:
                print(f'Laporan validasi: {report_path}')
        if not quiet:
            print('Tidak ada baris terjemahan yang diisi; tidak ada perubahan.')
        return empty_report
    original = bytearray(binary_path.read_bytes())
    plans, errors = [], []
    report_rows = []
    for row in chosen:
        try:
            try: csv_offset = int(row['offset_text'], 16)
            except ValueError: raise ValueError(f'file_offset_hex tidak valid: {row["offset_text"]!r}')
            offset, orig = get_original(original, row['id'], csv_offset)
            encoded = encode_text(row['translation'], row['id'], row['source'], message_index)
            if len(encoded) * 2 > TEXT_CAPACITY_BYTES:
                raise ValueError(f'teks memerlukan {len(encoded)*2} byte; kapasitas record {TEXT_CAPACITY_BYTES} byte')
            if message_index == 3 and row['id'] == 0x3A2 and orig[:3] != list(FACE_PREFIX):
                raise ValueError('kontrol awal asli 0x3A2 tidak sesuai; file mungkin bukan sumber asli')
            plans.append((row, offset, encoded))
            report_rows.append({
                'csv_line': row['line'], 'record_id': f'0x{row["id"]:X}',
                'status': 'valid', 'encoded_halfwords': len(encoded),
                'encoded_bytes': len(encoded) * 2, 'file_offset': f'0x{offset:X}',
                'message': ''
            })
        except (ValueError, struct.error) as e:
            msg = f'CSV baris {row["line"]}, record 0x{row["id"]:X}: {e}'
            errors.append(msg)
            report_rows.append({
                'csv_line': row['line'], 'record_id': f'0x{row["id"]:X}',
                'status': 'error', 'encoded_halfwords': None,
                'encoded_bytes': None, 'file_offset': row.get('offset_text',''),
                'message': str(e)
            })
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps({
            'csv': str(csv_path), 'bin': str(binary_path), 'message_index': message_index,
            'selected_records': len(chosen), 'valid_records': len(plans),
            'error_records': len(errors), 'check_only': check_only,
            'records': report_rows
        }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        if not quiet:
            print(f'Laporan validasi: {report_path}')
    if errors:
        print(f'VALIDASI GAGAL: {len(errors)} masalah; tidak ada record yang ditulis.', file=sys.stderr)
        for e in errors: print(' - ' + e, file=sys.stderr)
        raise SystemExit(2)
    if not quiet:
        print(f'Validasi OK: {len(plans)} record terjemahan; semua kapasitas dan offset lolos.')
        for row, offset, encoded in plans:
            print(f'  0x{row["id"]:X}: {len(encoded)} halfword ({len(encoded)*2} byte), offset 0x{offset:X}')
    if check_only:
        if not quiet:
            print('Mode check-only: file BIN tidak diubah.')
        return {'csv': str(csv_path), 'bin': str(binary_path), 'message_index': message_index, 'selected_records': len(chosen), 'valid_records': len(plans), 'error_records': 0, 'check_only': True, 'records': report_rows}
    out = bytearray(original)
    for row, offset, encoded in plans:
        out[offset:offset + TEXT_CAPACITY_BYTES] = bytes(TEXT_CAPACITY_BYTES)
        struct.pack_into('<' + 'H' * len(encoded), out, offset, *encoded)

    # Write a complete temporary file in the destination directory, then atomically
    # replace the destination. A failed write must not leave a partially-written BIN.
    destination = output_path or binary_path
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f'.{destination.name}.', suffix='.tmp', dir=str(destination.parent)
    )
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(out)
            f.flush()
            os.fsync(f.fileno())
        if destination.exists():
            try:
                os.chmod(temp_name, destination.stat().st_mode)
            except OSError:
                pass
        os.replace(temp_name, destination)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
    if not quiet:
        print(f'Berhasil menulis {len(plans)} record ke {destination}.')
    return {'csv': str(csv_path), 'bin': str(binary_path), 'output': str(destination), 'message_index': message_index, 'selected_records': len(chosen), 'valid_records': len(plans), 'error_records': 0, 'check_only': False, 'records': report_rows}


MESSAGE_FILES = {
    0: '02_messege0.bin',
    1: '03_messege1.bin',
    2: '04_messege2.bin',
    3: '05_messege3.bin',
    4: '06_messege4.bin',
}


def detect_message_index(path):
    """Infer message index from conventional filenames such as 03_messege1.bin."""
    match = re.search(r'messege([0-4])', Path(path).name, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _find_csv_for_message(csv_dir, index):
    preferred = csv_dir / f'messege{index}_translation_template.csv'
    if preferred.is_file():
        return preferred
    candidates = sorted(p for p in csv_dir.glob('*.csv')
                        if re.search(rf'messege{index}(?:_|\.)', p.name, re.IGNORECASE))
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise FileNotFoundError(
            f'CSV messege{index} tidak ditemukan; buat {preferred.name} '
            'atau sediakan tepat satu CSV bernama dengan pola *messegeN*.csv')
    names = ', '.join(p.name for p in candidates)
    raise ValueError(
        f'lebih dari satu CSV cocok untuk messege{index}: {names}; '
        f'gunakan nama standar {preferred.name} agar pemetaan tidak ambigu')


def run_batch(bin_dir, csv_dir, output_dir, check_only=False, report_path=None):
    """Preflight every message pair; only write outputs if all pairs validate."""
    bin_dir = Path(bin_dir)
    csv_dir = Path(csv_dir)
    output_dir = Path(output_dir)
    jobs = []
    for index, name in MESSAGE_FILES.items():
        binary_path = bin_dir / name
        if not binary_path.is_file():
            raise FileNotFoundError(f'BIN messege{index} tidak ditemukan: {binary_path}')
        csv_path = _find_csv_for_message(csv_dir, index)
        jobs.append((index, binary_path, csv_path))

    import tempfile as _tempfile
    preflight = []
    failures = []
    with _tempfile.TemporaryDirectory(prefix='hmbtn-translation-preflight-') as temp:
        temp_dir = Path(temp)
        for index, binary_path, csv_path in jobs:
            per_report = temp_dir / f'messege{index}.json'
            try:
                result = process(
                    binary_path, csv_path, check_only=True,
                    report_path=per_report, message_index=index, quiet=True)
                if per_report.exists():
                    result = json.loads(per_report.read_text(encoding='utf-8'))
                elif result is None:
                    result = {'message_index': index, 'bin': str(binary_path), 'csv': str(csv_path),
                              'selected_records': 0, 'valid_records': 0, 'error_records': 0,
                              'check_only': True, 'records': []}
                preflight.append(result)
            except SystemExit as exc:
                failures.append({'message_index': index, 'bin': str(binary_path),
                                 'csv': str(csv_path), 'exit_code': exc.code})
                if per_report.exists():
                    preflight.append(json.loads(per_report.read_text(encoding='utf-8')))
                else:
                    preflight.append({'message_index': index, 'bin': str(binary_path), 'csv': str(csv_path),
                                      'selected_records': None, 'valid_records': 0,
                                      'error_records': None, 'check_only': True, 'records': []})
        if failures:
            master = {
                'mode': 'batch', 'status': 'validation_failed',
                'bin_dir': str(bin_dir), 'csv_dir': str(csv_dir),
                'output_dir': str(output_dir), 'message_files': preflight,
                'batch_errors': failures, 'outputs_written': []
            }
            if report_path:
                report_path.parent.mkdir(parents=True, exist_ok=True)
                report_path.write_text(json.dumps(master, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            print(f'BATCH GAGAL: {len(failures)} pasangan BIN/CSV gagal validasi. Tidak ada output yang ditulis.', file=sys.stderr)
            raise SystemExit(2)

    if check_only:
        master = {
            'mode': 'batch', 'status': 'valid', 'check_only': True,
            'bin_dir': str(bin_dir), 'csv_dir': str(csv_dir),
            'output_dir': str(output_dir), 'message_files': preflight,
            'outputs_written': []
        }
        if report_path:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(master, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            print(f'Laporan batch: {report_path}')
        selected = sum(int(x.get('selected_records') or 0) for x in preflight)
        valid = sum(int(x.get('valid_records') or 0) for x in preflight)
        print(f'BATCH VALIDASI OK: 5 BIN diperiksa; {selected} record terjemahan valid ({valid} record lolos). Tidak ada BIN yang ditulis.')
        return master

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    # Validation of all five pairs has succeeded. Write each result to the requested
    # output directory; un-translated messages are copied byte-for-byte.
    for index, binary_path, csv_path in jobs:
        out_path = output_dir / binary_path.name
        result = process(binary_path, csv_path, check_only=False,
                         output_path=out_path, message_index=index, quiet=True)
        if result is None or int(result.get('selected_records') or 0) == 0:
            if binary_path.resolve() != out_path.resolve():
                shutil.copy2(binary_path, out_path)
        if out_path.exists():
            data_hash = hashlib.sha256(out_path.read_bytes()).hexdigest()
            outputs.append({'message_index': index, 'path': str(out_path),
                            'size_bytes': out_path.stat().st_size, 'sha256': data_hash})
        else:
            outputs.append({'message_index': index, 'path': str(out_path),
                            'status': 'no output created'})

    master = {
        'mode': 'batch', 'status': 'written', 'check_only': False,
        'bin_dir': str(bin_dir), 'csv_dir': str(csv_dir),
        'output_dir': str(output_dir), 'message_files': preflight,
        'outputs_written': outputs
    }
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(master, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(f'Laporan batch: {report_path}')
    print(f'BATCH SELESAI: {len(outputs)} BIN siap di {output_dir}.')
    return master


def main():
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--all', action='store_true',
                      help='proses messege0..messege4 dengan nama BIN/CSV standar')
    mode.add_argument('--bin', type=Path, help='satu BIN dialog hasil ekstraksi')
    p.add_argument('--csv', type=Path, help='CSV untuk --bin')
    p.add_argument('--message-index', type=int, choices=range(5),
                   help='indeks messege0..4 jika nama BIN tidak standar; dideteksi otomatis bila memungkinkan')
    p.add_argument('--bin-dir', type=Path, help='folder yang berisi 02_messege0.bin sampai 06_messege4.bin')
    p.add_argument('--csv-dir', type=Path, help='folder berisi lima CSV terjemahan')
    p.add_argument('--output-dir', type=Path, help='folder output; wajib untuk --all agar BIN sumber tidak tertimpa tanpa sengaja')
    p.add_argument('--record-id', help='proses satu record, misalnya 0x3A2; hanya untuk mode satu BIN')
    p.add_argument('--check-only', action='store_true', help='validasi tanpa mengubah BIN')
    p.add_argument('--output', type=Path, help='output BIN terpisah untuk mode satu BIN; default menimpa --bin secara atomik')
    p.add_argument('--report-json', type=Path, help='laporan validasi atau batch dalam JSON')
    a = p.parse_args()
    try:
        if a.all:
            if not a.bin_dir or not a.csv_dir or not a.output_dir:
                p.error('--all mewajibkan --bin-dir, --csv-dir, dan --output-dir')
            if a.csv or a.message_index is not None or a.record_id or a.output:
                p.error('--csv, --message-index, --record-id, dan --output tidak digunakan bersama --all')
            run_batch(a.bin_dir, a.csv_dir, a.output_dir, a.check_only, a.report_json)
        else:
            if not a.csv:
                p.error('mode --bin mewajibkan --csv')
            if a.bin_dir or a.csv_dir or a.output_dir:
                p.error('--bin-dir, --csv-dir, dan --output-dir hanya untuk --all')
            idx = a.message_index if a.message_index is not None else detect_message_index(a.bin)
            if a.record_id and not re.fullmatch(r'(?:0[xX])?[0-9A-Fa-f]+', a.record_id):
                p.error('--record-id harus berupa ID heksadesimal, misalnya 0x3A2')
            process(a.bin, a.csv, int(a.record_id, 16) if a.record_id else None,
                    a.check_only, a.output, a.report_json, idx)
    except (OSError, ValueError, csv.Error) as e:
        raise SystemExit(f'translate_messages.py: error: {e}')


if __name__ == '__main__':
    main()

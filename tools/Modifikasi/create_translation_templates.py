#!/usr/bin/env python3
"""Generate CSV translation templates for HMBTN messege0..messege4 BIN files.

Known glyphs and controls are decoded from the supplied source audit. Unidentified
halfwords are retained as <G:XXXX>; they are never guessed as ordinary characters.
Existing CSV seed data can be merged by record ID to preserve reviewed decoded text,
Indonesian translations, and review statuses.
"""
from __future__ import annotations
import argparse
import csv
import re
import struct
import sys
from pathlib import Path

RECORD_STRIDE = 0x2000
TEXT_OFFSET_IN_RECORD = 0x1800
TEXT_CAPACITY_BYTES = 0x0800
END = 0xFFFF

CONTROL_TAGS = {
    0x0F87: 'FACE',
    0x0FF1: 'SCROLL_HOLD',
    0x0FF3: 'NO_SCROLL',
    0x0FF4: 'FACE_SHOW',
    0x0FF5: 'FACE_RELOAD',
    0x0FF6: 'FACE_HIDE',
    0x0FF7: 'FACE_BANK',
    0x0FF8: 'CHOICE_4',
    0x0FF9: 'CHOICE_3',
    0x0FFA: 'CHOICE_2',
    0x0FFB: 'PAGE_END',
    0x0FFC: 'PAGE_BREAK',
    0x0FF2: 'NO_OP',
}

# Only glyphs supported by hmbtn-glyph-audit.md are mapped to visible characters.
# Unknown artwork remains explicit as <G:XXXX>.
SYMBOLS = {
    0x0050: '’t',
    0x0051: '’s',
    0x0054: '’m',
    0x0055: '’r',
    0x0061: '"',
    0x0062: '?',
    0x0063: '!',
    0x0064: '...',
    0x0066: ':',
    0x0067: ';',
    0x0068: '+',
    0x0069: '-',
    0x006A: '(',
    0x006B: ')',
    0x006C: '.',
    0x006D: '○',
    0x006E: '×',
    0x006F: '△',
    0x0070: '□',
    0x0071: '/',
    0x0074: '~',
    0x0076: '&',
    0x0077: '☆',
    0x0080: '♥',
    0x0081: '♡',
    0x008C: ',',
    0x008F: '%',
}

FIELDNAMES = [
    'record_id_hex', 'file_offset_hex', 'glyph_count',
    'decoded_text', 'indonesian_translation', 'review_status'
]
MESSAGE_FILES = {
    0: '02_messege0.bin',
    1: '03_messege1.bin',
    2: '04_messege2.bin',
    3: '05_messege3.bin',
    4: '06_messege4.bin',
}


def decode_word(word: int) -> str:
    if word == 0xFFFE:
        return '\r\n'
    if word == 0x0FFD:
        return ' '
    if word in CONTROL_TAGS:
        return f'<{CONTROL_TAGS[word]}>'
    if 0x0E25 <= word <= 0x0E2F:
        return f'<WAIT:{0x0E2F - word}>'
    if 0x4000 <= word <= 0x4FFF:
        return f'<INSERT:{word:04X}>'
    if 0x0000 <= word <= 0x0019:
        return chr(ord('A') + word)
    if 0x0020 <= word <= 0x0039:
        return chr(ord('a') + word - 0x0020)
    if 0x0040 <= word <= 0x0049:
        return chr(ord('0') + word - 0x0040)
    if word in SYMBOLS:
        return SYMBOLS[word]
    return f'<G:{word:04X}>'


def decode_record(data: bytes, rid: int) -> tuple[int, str]:
    offset = rid * RECORD_STRIDE + TEXT_OFFSET_IN_RECORD
    end_offset = offset + TEXT_CAPACITY_BYTES
    if end_offset > len(data):
        raise ValueError(f'record 0x{rid:X}: text area beyond BIN')
    words = struct.unpack_from('<' + 'H' * (TEXT_CAPACITY_BYTES // 2), data, offset)
    try:
        end_index = words.index(END)
    except ValueError as exc:
        raise ValueError(f'record 0x{rid:X}: terminator 0xFFFF not found') from exc
    decoded = ''.join(decode_word(w) for w in words[:end_index])
    return end_index, decoded


def normalize_header(name: str | None) -> str:
    value = (name or '').strip().lstrip('\ufeff')
    for known in ('Ã¯Â»Â¿', 'ï»¿'):
        while value.startswith(known):
            value = value[len(known):]
    return value


def load_seed(path: Path) -> dict[int, dict[str, str]]:
    with path.open('r', encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        headers = {normalize_header(h): h for h in (reader.fieldnames or [])}
        if 'record_id_hex' not in headers:
            raise ValueError(f'{path}: missing record_id_hex')
        rows: dict[int, dict[str, str]] = {}
        for line, row in enumerate(reader, 2):
            try:
                rid = int((row.get(headers['record_id_hex']) or '').strip(), 16)
            except ValueError:
                continue
            if rid in rows:
                raise ValueError(f'{path}: duplicate record ID 0x{rid:X} at CSV line {line}')
            rows[rid] = {
                normalize_header(k): (v or '') for k, v in row.items() if k is not None
            }
        return rows


def find_seed(seed_dir: Path, index: int) -> Path | None:
    preferred = seed_dir / f'messege{index}_translation_template.csv'
    if preferred.is_file():
        return preferred
    candidates = sorted(p for p in seed_dir.glob('*.csv')
                        if re.search(rf'messege{index}(?:_|\.)', p.name, re.IGNORECASE))
    if len(candidates) > 1:
        raise ValueError(f'multiple seed CSVs for messege{index}: ' + ', '.join(p.name for p in candidates))
    return candidates[0] if candidates else None


def generate_one(bin_path: Path, output_path: Path, index: int, seed_path: Path | None) -> dict:
    data = bin_path.read_bytes()
    if len(data) % RECORD_STRIDE:
        raise ValueError(f'{bin_path}: size {len(data)} is not divisible by record stride 0x{RECORD_STRIDE:X}')
    seed = load_seed(seed_path) if seed_path else {}
    record_count = len(data) // RECORD_STRIDE
    extras = sorted(set(seed) - set(range(record_count)))
    if extras:
        raise ValueError(f'{seed_path}: seed has record IDs outside BIN: ' + ', '.join(f'0x{x:X}' for x in extras[:10]))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, lineterminator='\n')
        writer.writeheader()
        for rid in range(record_count):
            glyph_count, decoded_generated = decode_record(data, rid)
            offset = rid * RECORD_STRIDE + TEXT_OFFSET_IN_RECORD
            old = seed.get(rid, {})
            if old.get('file_offset_hex'):
                try:
                    old_offset = int(old['file_offset_hex'], 16)
                except ValueError as exc:
                    raise ValueError(f'{seed_path}: invalid offset for record 0x{rid:X}') from exc
                if old_offset != offset:
                    raise ValueError(f'{seed_path}: offset mismatch record 0x{rid:X}: CSV 0x{old_offset:X}, BIN 0x{offset:X}')
            if old.get('glyph_count'):
                try:
                    old_count = int(old['glyph_count'], 0)
                except ValueError:
                    try:
                        old_count = int(old['glyph_count'])
                    except ValueError as exc:
                        raise ValueError(f'{seed_path}: invalid glyph_count for record 0x{rid:X}') from exc
                if old_count != glyph_count:
                    raise ValueError(f'{seed_path}: glyph_count mismatch record 0x{rid:X}: CSV {old_count}, BIN {glyph_count}')
            # Keep the audited source text from the existing CSV where available.
            # Newly generated messages use the conservative source-based decoder above.
            decoded = old.get('decoded_text') or decoded_generated
            writer.writerow({
                'record_id_hex': f'0x{rid:03X}',
                'file_offset_hex': f'0x{offset:06X}',
                'glyph_count': glyph_count,
                'decoded_text': decoded,
                'indonesian_translation': old.get('indonesian_translation', ''),
                'review_status': old.get('review_status', 'BELUM') or 'BELUM',
            })
    return {
        'message_index': index,
        'bin': str(bin_path),
        'seed_csv': str(seed_path) if seed_path else None,
        'output_csv': str(output_path),
        'record_count': record_count,
        'seeded_records': len(seed),
        'size_bytes': output_path.stat().st_size,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bin-dir', required=True, type=Path,
                   help='folder containing 02_messege0.bin ... 06_messege4.bin')
    p.add_argument('--output-dir', required=True, type=Path,
                   help='directory to write the five standard translation CSV templates')
    p.add_argument('--existing-csv-dir', type=Path,
                   help='optional folder with existing CSVs to merge by record ID')
    p.add_argument('--report-json', type=Path, help='optional generation report JSON')
    a = p.parse_args()
    try:
        summaries = []
        for index, filename in MESSAGE_FILES.items():
            bin_path = a.bin_dir / filename
            if not bin_path.is_file():
                raise FileNotFoundError(f'missing BIN for messege{index}: {bin_path}')
            seed = find_seed(a.existing_csv_dir, index) if a.existing_csv_dir else None
            out = a.output_dir / f'messege{index}_translation_template.csv'
            summaries.append(generate_one(bin_path, out, index, seed))
        if a.report_json:
            a.report_json.parent.mkdir(parents=True, exist_ok=True)
            import json
            a.report_json.write_text(json.dumps({'status': 'generated', 'messages': summaries},
                                                ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        for item in summaries:
            print(f"messege{item['message_index']}: {item['record_count']} records -> {item['output_csv']} ({item['size_bytes']:,} bytes)")
        print('Selesai: lima CSV template dibuat. Glyph yang belum terverifikasi tetap berupa <G:XXXX>.')
        return 0
    except (OSError, ValueError, csv.Error) as exc:
        print(f'create_translation_templates.py: error: {exc}', file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())

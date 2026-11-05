"""Post-integration binary validation with strict patch-range accounting.

Validation compares an original image, a patched image, and the exact
IntegrationPlan produced for that original image. It never modifies either
image or attempts to infer permitted patch locations.
"""
from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass

from .integration import IntegrationPlan


class ValidationError(ValueError):
    """Raised when an integrated image violates its recorded plan."""


@dataclass(frozen=True)
class ValidationReport:
    original_sha256: str
    output_sha256: str
    image_size: int
    authorized_ranges: tuple[tuple[int, int, str], ...]
    changed_ranges: tuple[tuple[int, int], ...]

    def to_dict(self) -> dict:
        return {
            "valid": True,
            "original_sha256": self.original_sha256,
            "output_sha256": self.output_sha256,
            "image_size": self.image_size,
            "authorized_ranges": [
                {"start": f"0x{start:X}", "end": f"0x{end:X}", "id": label}
                for start, end, label in self.authorized_ranges
            ],
            "changed_ranges": [
                {"start": f"0x{start:X}", "end": f"0x{end:X}"}
                for start, end in self.changed_ranges
            ],
        }


def _hex_word(value: str, field: str) -> int:
    if not isinstance(value, str) or not value.startswith("0x"):
        raise ValidationError(f"{field} must be a 0x-prefixed hexadecimal word")
    try:
        result = int(value, 16)
    except ValueError as exc:
        raise ValidationError(f"{field} is not valid hexadecimal") from exc
    if result < 0 or result > 0xFFFFFFFF:
        raise ValidationError(f"{field} is outside the 32-bit range")
    return result


def _word_bytes(words: list[str] | tuple[str, ...], field: str) -> bytes:
    if not isinstance(words, (list, tuple)) or not words:
        raise ValidationError(f"{field} must be a non-empty word array")
    try:
        values = [_hex_word(word, field) for word in words]
        return struct.pack("<" + "I" * len(values), *values)
    except (struct.error, TypeError) as exc:
        raise ValidationError(f"{field} contains invalid words") from exc


def _range(offset: int, size: int, image_size: int, label: str) -> tuple[int, int, str]:
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise ValidationError(f"{label}: invalid file offset")
    end = offset + size
    if end > image_size:
        raise ValidationError(f"{label}: patch range exceeds image size")
    return offset, end, label


def validate_integrated_image(
    original: bytes | bytearray, output: bytes | bytearray, plan: IntegrationPlan,
) -> ValidationReport:
    """Verify hashes, exact planned bytes, image size, and all untouched bytes."""
    if not isinstance(original, (bytes, bytearray)) or not isinstance(output, (bytes, bytearray)):
        raise ValidationError("original and output images must be bytes or bytearray")
    original = bytes(original)
    output = bytes(output)
    if not isinstance(plan, IntegrationPlan):
        raise ValidationError("plan must be an IntegrationPlan instance")
    if len(original) != len(output):
        raise ValidationError(
            f"image size changed: original={len(original)}, output={len(output)}"
        )

    original_hash = hashlib.sha256(original).hexdigest()
    output_hash = hashlib.sha256(output).hexdigest()
    if original_hash != plan.image_sha256:
        raise ValidationError("original image SHA-256 does not match the integration plan")

    authorized: list[tuple[int, int, str]] = []
    expected_writes: list[tuple[int, bytes, str]] = []
    for index, entry in enumerate(plan.entries):
        if not isinstance(entry, dict) or not isinstance(entry.get("patch"), dict):
            raise ValidationError(f"plan entry {index} is malformed")
        patch = entry["patch"]
        entry_id = entry.get("id")
        if not isinstance(entry_id, str) or not entry_id:
            raise ValidationError(f"plan entry {index} has no valid id")
        kind = entry.get("type")

        if kind == "jal":
            offset = int(patch["file_offset"], 16)
            expected = _hex_word(patch["expected_word"], f"{entry_id}.expected_word")
            replacement = _hex_word(patch["replacement_word"], f"{entry_id}.replacement_word")
            if offset & 3:
                raise ValidationError(f"{entry_id}: JAL offset is unaligned")
            if original[offset:offset + 4] != struct.pack("<I", expected):
                raise ValidationError(f"{entry_id}: original JAL word differs from plan")
            region = _range(offset, 4, len(original), entry_id)
            authorized.append(region)
            expected_writes.append((offset, struct.pack("<I", replacement), entry_id))
        elif kind == "hook":
            site = int(patch["site_offset"], 16)
            trampoline = int(patch["trampoline_offset"], 16)
            original_words = _word_bytes(patch["original_words"], f"{entry_id}.original_words")
            hook_words = _word_bytes(patch["hook_words"], f"{entry_id}.hook_words")
            expected_trampoline = bytes.fromhex(patch["expected_trampoline"])
            trampoline_words = _word_bytes(
                patch["trampoline_words"], f"{entry_id}.trampoline_words"
            )
            if len(original_words) != 8 or len(hook_words) != 8:
                raise ValidationError(f"{entry_id}: hook site must contain two words")
            if len(expected_trampoline) != 16 or len(trampoline_words) != 16:
                raise ValidationError(f"{entry_id}: trampoline must contain four words")
            if original[site:site + 8] != original_words:
                raise ValidationError(f"{entry_id}: original hook words differ from plan")
            if original[trampoline:trampoline + 16] != expected_trampoline:
                raise ValidationError(f"{entry_id}: original trampoline bytes differ from plan")
            authorized.extend([
                _range(site, 8, len(original), entry_id + ":site"),
                _range(trampoline, 16, len(original), entry_id + ":trampoline"),
            ])
            expected_writes.extend([
                (site, hook_words, entry_id + ":site"),
                (trampoline, trampoline_words, entry_id + ":trampoline"),
            ])
        else:
            raise ValidationError(f"{entry_id}: unsupported plan entry type {kind!r}")

    authorized.sort()
    for previous, current in zip(authorized, authorized[1:]):
        if current[0] < previous[1]:
            raise ValidationError(
                f"authorized patch ranges overlap: {previous[2]} and {current[2]}"
            )

    for offset, expected_bytes, label in expected_writes:
        if output[offset:offset + len(expected_bytes)] != expected_bytes:
            raise ValidationError(f"{label}: output bytes do not match planned patch")

    changed_offsets = [
        index for index, (before, after) in enumerate(zip(original, output))
        if before != after
    ]
    actual_changed_ranges: list[tuple[int, int]] = []
    for offset in changed_offsets:
        if actual_changed_ranges and offset == actual_changed_ranges[-1][1]:
            start, _ = actual_changed_ranges[-1]
            actual_changed_ranges[-1] = (start, offset + 1)
        else:
            actual_changed_ranges.append((offset, offset + 1))

    for start, end in actual_changed_ranges:
        if not any(start >= allowed_start and end <= allowed_end
                   for allowed_start, allowed_end, _ in authorized):
            raise ValidationError(
                f"unexpected modification outside authorized patch ranges at "
                f"0x{start:X}-0x{end:X}"
            )

    # Report complete authorized patch units, but only when bytes changed.
    changed_ranges = [
        (start, end) for start, end, _ in authorized
        if original[start:end] != output[start:end]
    ]

    return ValidationReport(
        original_sha256=original_hash,
        output_sha256=output_hash,
        image_size=len(original),
        authorized_ranges=tuple(authorized),
        changed_ranges=tuple(changed_ranges),
    )

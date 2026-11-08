#!/usr/bin/env python3
"""Write objdiff.json for the progress report (decomp.dev).

usage: python3 tools/objdiff_config.py BUILD_DIR > objdiff.json

One unit per C file of the game, in a category per image (the EXE, each overlay).
The PSY-Q library objects the EXE links are Sony's own and are not counted.

Every unit's target and base are the same built object, and every unit is complete:
run this only after `cmake --build BUILD_DIR --target check` passed, which proves each
linked image byte-identical to the original's (disc/binaries.sha1).
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def image_of(source):
    """The image a source file belongs to: `main` for the EXE, else the overlay's name."""
    parts = source.relative_to(ROOT / "src").parts
    return "main" if parts[0] == "main" else parts[1]


def main():
    build = Path(sys.argv[1])
    # Mod-owned replacement translation units retain their original logical
    # names in progress reporting; excluded originals must not produce units.
    rucksack_original = ROOT / "src/overlay/11_GF_FARM/menu/storage_swap.c"
    rucksack_mod = ROOT / "src/overlay/11_GF_FARM/Modifikasi/ransel_mod.c"
    player_original = ROOT / "src/overlay/11_GF_FARM/people/player.c"
    player_mod = ROOT / "src/overlay/11_GF_FARM/Modifikasi/player_mod.c"
    farm_frame_original = ROOT / "src/overlay/11_GF_FARM/farm_frame.c"
    farm_frame_mod = ROOT / "src/overlay/11_GF_FARM/Modifikasi/farm_frame_mod.c"
    animals_original = ROOT / "src/overlay/11_GF_FARM/animals/animals.c"
    animals_mod = ROOT / "src/overlay/11_GF_FARM/Modifikasi/animals_mod.c"

    excluded_sources = {
        rucksack_original,
        player_original,
        farm_frame_original,
        animals_original,
    }
    replacement_units = {
        rucksack_mod: "overlay/11_GF_FARM/menu/storage_swap",
        player_mod: "overlay/11_GF_FARM/people/player",
        farm_frame_mod: "overlay/11_GF_FARM/farm_frame",
        animals_mod: "overlay/11_GF_FARM/animals/animals",
    }

    sources = sorted(
        p for p in (ROOT / "src").rglob("*.c")
        if p not in excluded_sources
    )
    units, images = [], []
    for source in sources:
        relative = source.relative_to(ROOT / "src").with_suffix("")
        unit_name = relative.as_posix()
        if source in replacement_units:
            unit_name = replacement_units[source]
        obj = (build / "src" / relative).with_suffix(".o").as_posix()
        image = image_of(source)
        if image not in images:
            images.append(image)
        units.append({
            "name": unit_name,
            "target_path": obj,
            "base_path": obj,
            "metadata": {
                "complete": True,
                "source_path": source.relative_to(ROOT).as_posix(),
                "progress_categories": [image],
            },
        })
    categories = [{"id": image, "name": "SLUS_011.15" if image == "main" else image}
                  for image in images]
    json.dump({
        "$schema": "https://raw.githubusercontent.com/encounter/objdiff/main/config.schema.json",
        "build_target": False,
        "build_base": False,
        "units": units,
        "progress_categories": categories,
    }, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()

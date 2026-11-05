/*
 * Walk-through crop collision helper for the FARM overlay.
 *
 * The original farm_tile_state() is local to farm_probe.c. This replacement
 * keeps its tile-rule behavior for non-crops and reports crop cells as open.
 * The JAL registry will route farm_probe_steps() through this function.
 */
#include "farm_state.h"
#include "farm_tables.h"
#include "field/field.h"
#include "items.h"

s32 mod_farm_tile_state(s16 column, s16 row, s32 mode)
{
    FarmFieldTile *record;
    ItemInfo *entry;
    s16 ruleIndex;
    s32 status;

    if (mode != 0) {
        record = &game_state.slots7x7[row].rows[column];
    } else {
        record = &game_state.fieldTiles[row].rows[column];
    }

    if (record->value == ITEM_SOIL) {
        return 2;
    }

    entry = game_state.itemInfo;
    if (record->value < ITEM_COUNT && entry[record->value].crop != CROP_NONE) {
        return 0;
    }

    ruleIndex = entry[record->value].tileRule[record->kind];
    status = game_state.tileRules[ruleIndex].status;

    switch (status) {
    case TILE_RULE_BLOCKED:
        return 1;
    case TILE_RULE_NONE:
        return 2;
    case TILE_RULE_OPEN:
        return 0;
    default:
        return 0;
    }
}

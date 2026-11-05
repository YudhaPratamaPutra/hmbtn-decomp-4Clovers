/*
 * Crop pass-through replacement for the FARM tile-state query.
 *
 * Keep the original tile-rule result for every non-crop tile. Crop records
 * are reported as open so farm_probe_steps can walk through planted cells.
 */
#include "farm_state.h"
#include "farm_tables.h"
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

/*
 * Crop pass-through replacement for the FARM tile-state query.
 *
 * Keep the original tile-rule result for every non-crop tile. Crop records
 * are reported as open so farm_probe_steps can walk through planted cells.
 */
#include "farm_state.h"
#include "farm_tables.h"
#include "field.h"
#include "items.h"
#include "mips_auto_hook.h"

MIPS_AUTO_HOOK_TRAMPOLINE(farm_tile_state_trampoline);

/* MIPS_AUTO_HOOK: {"id":"farm-no-plant-collision","type":"hook","site_symbol":"farm_tile_state","trampoline_symbol":"farm_tile_state_trampoline"} */
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
    if (record->value >= ITEM_COUNT) {
        return 0;
    }
    if (entry[record->value].crop != CROP_NONE) {
        return 0;
    }

    ruleIndex = entry[record->value].tileRule[record->kind];
    if (ruleIndex < 0) {
        return 2;
    }
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

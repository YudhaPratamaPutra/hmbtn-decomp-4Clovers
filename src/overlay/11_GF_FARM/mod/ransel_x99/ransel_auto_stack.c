/* Ransel X99 - DIAG A: all ransel code compiled in, hook is pure passthrough */
#include <sys/types.h>
#include "types.h"
#include "farm_shared.h"
#include "player.h"
#include "picture_cells.h"
#include "mips_auto_hook.h"

#define RANSEL_STACK_MAX 99
MIPS_AUTO_HOOK_TRAMPOLINE(ransel_x99_frame_trampoline);

static s32 ransel_compact_table(FarmStoredItem *table, s32 count)
{
    s32 index, search;
    for (index = 0; index < count; index++) {
        if (table[index].id == 0) {
            for (search = index + 1; search < count; search++) {
                if (table[search].id != 0) {
                    table[index].id = table[search].id;
                    table[index].modifier = table[search].modifier;
                    table[index].count = table[search].count;
                    table[search].id = 0; table[search].modifier = 0; table[search].count = 0;
                    break;
                }
            }
        }
    }
    return 0;
}

static s32 ransel_stack_held_item(FarmPlayer *player)
{
    FarmStoredItem *held, *slot;
    s32 remaining, capacity, amount, i, slots;
    if (player == 0) return 0;
    slots = player->itemSlots;
    if (slots <= 0 || slots > PLAYER_BAG_SLOTS) slots = PLAYER_BAG_SLOTS;
    held = &player->held[HELD_ITEM];
    if (held->id == 0) return 1;
    remaining = held->count;
    if (remaining <= 0) {
        for (i = 0; i < slots; i++) {
            slot = &player->items[i];
            if (slot->id == 0) { stored_item_copy(slot, held); stored_item_clear(held); ransel_compact_table(player->items, slots); return 1; }
        }
        return 0;
    }
    for (i = 0; i < slots && remaining > 0; i++) {
        slot = &player->items[i];
        if (slot->id == held->id && slot->count < RANSEL_STACK_MAX) {
            capacity = RANSEL_STACK_MAX - slot->count;
            amount = remaining < capacity ? remaining : capacity;
            slot->count += amount; remaining -= amount;
        }
    }
    for (i = 0; i < slots && remaining > 0; i++) {
        slot = &player->items[i];
        if (slot->id == 0) {
            amount = remaining > RANSEL_STACK_MAX ? RANSEL_STACK_MAX : remaining;
            stored_item_copy(slot, held); slot->count = amount; remaining -= amount;
        }
    }
    if (remaining == 0) { stored_item_clear(held); ransel_compact_table(player->items, slots); return 1; }
    held->count = remaining;
    return 0;
}

/* MIPS_AUTO_HOOK: {"id":"ransel-x99-frame-update","type":"hook","site_symbol":"player_frame_update","trampoline_symbol":"ransel_x99_frame_trampoline"} */
void mod_ransel_x99_frame_update(void)
{
    ((void (*)(void))(void *)ransel_x99_frame_trampoline)();
}

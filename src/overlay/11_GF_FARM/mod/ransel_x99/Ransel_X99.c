#include "Ransel_X99.h"

static void player_rucksack_stack_item(FarmPlayer *player)
{
    FarmStoredItem *held;
    FarmStoredItem *slot;
    s32 remaining;
    s32 capacity;
    s32 amount;
    s32 i;

    held = &player->held[HELD_ITEM];
    remaining = held->count;

    if (held->id == 0 || remaining <= 0)
    {
        return;
    }

    /* Gabungkan dengan tumpukan item ber-ID sama. */
    for (i = 0; i < player->itemSlots && remaining > 0; i++)
    {
        slot = &player->items[i];

        if (slot->id == held->id && slot->count < 99)
        {
            capacity = 99 - slot->count;
            amount = remaining < capacity ? remaining : capacity;

            slot->count += amount;
            remaining -= amount;
        }
    }

    /* Masukkan ke slot kosong jika masih ada sisa. */
    for (i = 0; i < player->itemSlots && remaining > 0; i++)
    {
        slot = &player->items[i];

        if (slot->id == 0)
        {
            amount = remaining > 99 ? 99 : remaining;

            stored_item_copy(slot, held);
            slot->count = amount;
            remaining -= amount;
        }
    }

    if (remaining == 0)
    {
        stored_item_clear(held);
        player_compact_items();
    }
    else
    {
        held->count = remaining;
    }
}

case PLAYER_MODE_STORE_ITEM:
    if (!item_is_print(player->held[HELD_ITEM].id))
    {
        player_rucksack_stack_item(player);
    }
    else
    {
        picture_release_item(player->held[HELD_ITEM].id);
        stored_item_clear(&player->held[HELD_ITEM]);
    }

    player->stateFlags &= ~PLAYER_FLAG_CARRY_ITEM;
    player_reset_pose();
    return 0;
    
    static void player_carry_tick(void)
{
    FarmPlayer *player = &game_state.player;
    FarmStoredItem *slot;
    s32 i;
    s32 can_store;

    if (!(player->stateFlags & PLAYER_FLAG_CARRY_ITEM))
    {
        player_reset_pose();
        return;
    }

    player_compact_items();

    can_store = 0;

    for (i = 0; i < player->itemSlots; i++)
    {
        slot = &player->items[i];

        if (slot->id == 0 ||
            (slot->id == player->held[HELD_ITEM].id &&
             slot->count < 99))
        {
            can_store = 1;
            break;
        }
    }

    if (can_store)
    {
        sound_play(8);
        player_set_mode(player, PLAYER_MODE_STORE_ITEM,
                        player->facing38 + 0x1D, -2);
        player->stateFlags &= ~PLAYER_FLAG_SHOWING_ITEM;
    }
}

/* Ransel X99 - auto-stack item di tangan ke rucksack.
 * Tanpa definisi fungsi mod tambahan (inline di hook) agar aman dari masalah
 * layout/link overlay. Hook selalu meneruskan ke body asli via trampoline.
 */
#include <sys/types.h>
#include "types.h"
#include "farm_shared.h"
#include "player.h"
#include "picture_cells.h"
#include "mips_auto_hook.h"

#define RANSEL_STACK_MAX 99

MIPS_AUTO_HOOK_TRAMPOLINE(ransel_x99_frame_trampoline);

/* MIPS_AUTO_HOOK: {"id":"ransel-x99-frame-update","type":"hook","site_symbol":"player_frame_update","trampoline_symbol":"ransel_x99_frame_trampoline"} */
void mod_ransel_x99_frame_update(void)
{
    if ((game_state.globalFlags & (GLOBAL_FLAG_PAUSED | GLOBAL_FLAG_MENU_OPEN | GLOBAL_FLAG_TRANSITION)) == 0)
    {
        FarmPlayer *player = &game_state.player;
        if ((player->stateFlags & (PLAYER_FLAG_CARRY_ITEM | PLAYER_FLAG_SCENE_CHANGE | PLAYER_FLAG_SCRIPTED)) == PLAYER_FLAG_CARRY_ITEM)
        {
            FarmStoredItem *held = &player->held[HELD_ITEM];
            if (held->id != 0)
            {
                s32 slots = player->itemSlots;
                if (slots <= 0 || slots > PLAYER_BAG_SLOTS)
                    slots = PLAYER_BAG_SLOTS;

                if (held->count <= 0)
                {
                    /* count <= 0: simpan sebagai item satu per satu */
                    s32 i;
                    for (i = 0; i < slots; i++)
                    {
                        if (player->items[i].id == 0)
                        {
                            stored_item_copy(&player->items[i], held);
                            stored_item_clear(held);
                            /* compact */
                            {
                                s32 a, b;
                                for (a = 0; a < slots; a++) {
                                    if (player->items[a].id == 0) {
                                        for (b = a + 1; b < slots; b++) {
                                            if (player->items[b].id != 0) {
                                                player->items[a] = player->items[b];
                                                player->items[b].id = 0;
                                                player->items[b].modifier = 0;
                                                player->items[b].count = 0;
                                                break;
                                            }
                                        }
                                    }
                                }
                            }
                            break;
                        }
                    }
                }
                else
                {
                    s32 remaining = held->count;
                    s32 i;
                    /* isi tumpukan yang sama dulu */
                    for (i = 0; i < slots && remaining > 0; i++)
                    {
                        if (player->items[i].id == held->id && player->items[i].count < RANSEL_STACK_MAX)
                        {
                            s32 cap = RANSEL_STACK_MAX - player->items[i].count;
                            s32 amt = remaining < cap ? remaining : cap;
                            player->items[i].count += amt;
                            remaining -= amt;
                        }
                    }
                    /* sisanya ke slot kosong */
                    for (i = 0; i < slots && remaining > 0; i++)
                    {
                        if (player->items[i].id == 0)
                        {
                            s32 amt = remaining > RANSEL_STACK_MAX ? RANSEL_STACK_MAX : remaining;
                            stored_item_copy(&player->items[i], held);
                            player->items[i].count = amt;
                            remaining -= amt;
                        }
                    }
                    if (remaining == 0)
                    {
                        stored_item_clear(held);
                        /* compact */
                        {
                            s32 a, b;
                            for (a = 0; a < slots; a++) {
                                if (player->items[a].id == 0) {
                                    for (b = a + 1; b < slots; b++) {
                                        if (player->items[b].id != 0) {
                                            player->items[a] = player->items[b];
                                            player->items[b].id = 0;
                                            player->items[b].modifier = 0;
                                            player->items[b].count = 0;
                                            break;
                                        }
                                    }
                                }
                            }
                        }
                    }
                    else
                    {
                        held->count = remaining;
                    }
                }
            }
        }
    }

    ((void (*)(void))(void *)ransel_x99_frame_trampoline)();
}

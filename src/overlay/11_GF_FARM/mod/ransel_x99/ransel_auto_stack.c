/* Ransel X99 - auto-stack item tertanggung di tangan ke rucksack.
 *
 * Fitur: setiap frame, jika player membawa item di tangan, coba tumpukkan
 * ke slot rucksack yang mengandung item sama (maks 99 per tumpukan), sisanya
 * ke slot kosong, lalu rapikan tabel.
 *
 * Arsitektur (menggantikan player_mod.c salinan penuh):
 *   - people/player.c ASLI tetap dibangun utuh, tidak diubah.
 *   - File ini hanya menambah satu hook bernama MIPS_AUTO_HOOK ke fungsi
 *     player_frame_update. Integrator menukar 8 byte pertama fungsi asli
 *     dengan `J mod_ransel_x99_frame_update; nop`, dan menulis 2 instruksi
 *     asli yang tergeser + `J player_frame_update+8` ke slot trampoline.
 *   - Setelah logika mod, hook memanggil trampoline sehingga isi asli
 *     player_frame_update tetap dijalankan selalu (body tidak pernah hilang).
 *   - Logika mod hanya berjalan saat gameplay normal dan player benar-benar
 *     membawa item, jadi tidak mengganggu fase loading/transisi farm.
 */

#include <sys/types.h>

#include "types.h"
#include "farm_shared.h"    /* game_state, GLOBAL_FLAG_* */
#include "player.h"         /* FarmPlayer, PLAYER_FLAG_*, HELD_ITEM, PLAYER_BAG_SLOTS */
#include "picture_cells.h"  /* FarmStoredItem, stored_item_copy, stored_item_clear */
#include "storage_swap.h"
#include "mips_auto_hook.h"

/* content_max: isi maksimum satu tumpukan rucksack. */
#define RANSEL_STACK_MAX 99

/* Trampoline milik hook ini: 16 byte di section .mips_trampoline.11_GF_FARM
 * diisi integrator dengan [instruksi asli 1][instruksi asli 2][J site+8][nop].
 * Jangan diganti atau dibagi antar hook. */
MIPS_AUTO_HOOK_TRAMPOLINE(ransel_x99_frame_trampoline);

/* Geser semua entri terisi ke depan tabel supaya tidak ada lubang di tengah. */
static s32 ransel_compact_table(FarmStoredItem *table, s32 count)
{
    s32 index;
    s32 search;

    for (index = 0; index < count; index++)
    {
        if (table[index].id == 0)
        {
            for (search = index + 1; search < count; search++)
            {
                if (table[search].id != 0)
                {
                    table[index].id = table[search].id;
                    table[index].modifier = table[search].modifier;
                    table[index].count = table[search].count;
                    table[search].id = 0;
                    table[search].modifier = 0;
                    table[search].count = 0;
                    break;
                }
            }
        }
    }
    return 0;
}

/* Tumpukkan item di tangan ke rucksack player. Mengembalikan 1 saat semua
 * item habis masuk (tangan bersih), 0 saat masih ada sisa di tangan. */
static s32 ransel_stack_held_item(FarmPlayer *player)
{
    FarmStoredItem *held;
    FarmStoredItem *slot;
    s32 remaining;
    s32 capacity;
    s32 amount;
    s32 i;

    held = &player->held[HELD_ITEM];
    if (held->id == 0)
    {
        return 1;
    }

    remaining = held->count;

    /* Rekap count <= 0 disimpan sebagai item satu per satu, tidak digabung. */
    if (remaining <= 0)
    {
        for (i = 0; i < player->itemSlots; i++)
        {
            slot = &player->items[i];
            if (slot->id == 0)
            {
                stored_item_copy(slot, held);
                stored_item_clear(held);
                ransel_compact_table(player->items, PLAYER_BAG_SLOTS);
                return 1;
            }
        }
        return 0;
    }

    /* Isi dulu tumpukan item yang sama yang belum penuh. */
    for (i = 0; i < player->itemSlots && remaining > 0; i++)
    {
        slot = &player->items[i];
        if (slot->id == held->id && slot->count < RANSEL_STACK_MAX)
        {
            capacity = RANSEL_STACK_MAX - slot->count;
            amount = remaining < capacity ? remaining : capacity;
            slot->count += amount;
            remaining -= amount;
        }
    }

    /* Sisanya masuk slot rucksack kosong. */
    for (i = 0; i < player->itemSlots && remaining > 0; i++)
    {
        slot = &player->items[i];
        if (slot->id == 0)
        {
            amount = remaining > RANSEL_STACK_MAX ? RANSEL_STACK_MAX : remaining;
            stored_item_copy(slot, held);
            slot->count = amount;
            remaining -= amount;
        }
    }

    if (remaining == 0)
    {
        stored_item_clear(held);
        ransel_compact_table(player->items, PLAYER_BAG_SLOTS);
        return 1;
    }

    held->count = remaining;
    return 0;
}

/* Dipasang sebagai entry-hook player_frame_update oleh auto-integrator:
 * logika ransel dijalankan dulu, lalu body asli player_frame_update dieksekusi
 * lewat trampoline ([2 instruksi asli][J player_frame_update+8][nop]). */
/* MIPS_AUTO_HOOK: {"id":"ransel-x99-frame-update","type":"hook","site_symbol":"player_frame_update","trampoline_symbol":"ransel_x99_frame_trampoline"} */
void mod_ransel_x99_frame_update(void)
{
    FarmPlayer *player = &game_state.player;

    if ((game_state.globalFlags & GLOBAL_FLAG_PAUSED) == 0
        && (player->stateFlags & (PLAYER_FLAG_CARRY_ITEM | PLAYER_FLAG_SCENE_CHANGE)) == PLAYER_FLAG_CARRY_ITEM)
    {
        ransel_stack_held_item(player);
    }

    /* Jalankan isi asli player_frame_update - tanpa ini state per-frame farm
     * (input, transisi, "Now Loading") tidak pernah jalan. */
    ((void (*)(void))(void *)ransel_x99_frame_trampoline)();
}

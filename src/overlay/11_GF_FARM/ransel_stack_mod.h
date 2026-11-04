#ifndef RANSEL_STACK_MOD_H
#define STORAGE_RANSEL_SWAP_H

/* Swapping items between the stores and the player. */

#include <sys/types.h>
#include <libgte.h>
#include <libgpu.h>
#include <libgs.h>

void storage_swap_begin(void);
void storage_swap_tick(void);
void farm_ransel_unpause(void);
void picture_cell_place_ransel_item(FarmStoredItem *item);
void picture_cell_ransel_build_prim(s16 key, s16 part, u_long *object, s16 u, s16 v, s32 flags);
s32 item_ransel_class_word_negative(s16 item);
s8 item_ransel_category(s16 item);
s16 stored_ransel_item_contents(FarmStoredItem *item);



#endif /* STORAGE_RANSEL_SWAP_H */

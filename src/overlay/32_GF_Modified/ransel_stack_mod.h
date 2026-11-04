#ifndef STORAGE_RANSEL_SWAP_H
#define STORAGE_RANSEL_SWAP_H

/* Swapping items between the stores and the player. */

#include <sys/types.h>
#include <libgte.h>
#include <libgpu.h>
#include <libgs.h>

void storage_ransel_swap_begin(void);
void storage_ransel_swap_tick(void);
void farm_ransel_unpause(void);
s32 item_ransel_class_word_negative(s16 item);

#endif /* STORAGE_RANSEL_SWAP_H */

#ifndef STORAGE_RANSEL_SWAP_H
#define STORAGE_RANSEL_SWAP_H

/* Swapping items between the stores and the player. */

#include <sys/types.h>
#include <libgte.h>
#include <libgpu.h>
#include <libgs.h>

void storage_ransel_swap_begin(void);
void storage_ransel_swap_tick(void);


#endif /* STORAGE_RANSEL_SWAP_H */

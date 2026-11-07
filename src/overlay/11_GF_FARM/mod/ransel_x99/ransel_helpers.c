/* Diag D: ransel stubs in a SEPARATE TU (never called) */
#include <sys/types.h>
#include "types.h"
#include "farm_shared.h"
#include "player.h"
#include "picture_cells.h"

static s32 ransel_compact_table(FarmStoredItem *table, s32 count)
{
    (void)table; (void)count;
    return 0;
}

static s32 ransel_stack_held_item(FarmPlayer *player)
{
    (void)player;
    return 0;
}

/* reference to prevent being obviously unused in some toolchains? keep static, not called */
void ransel_diag_anchor(void) { (void)ransel_compact_table; (void)ransel_stack_held_item; }

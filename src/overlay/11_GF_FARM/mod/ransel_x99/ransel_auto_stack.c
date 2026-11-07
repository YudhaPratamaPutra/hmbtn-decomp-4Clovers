/* Diag C: headers + stub ransel functions (empty bodies), passthrough hook */
#include <sys/types.h>
#include "types.h"
#include "farm_shared.h"
#include "player.h"
#include "picture_cells.h"
#include "mips_auto_hook.h"

MIPS_AUTO_HOOK_TRAMPOLINE(ransel_x99_frame_trampoline);

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

/* MIPS_AUTO_HOOK: {"id":"ransel-x99-frame-update","type":"hook","site_symbol":"player_frame_update","trampoline_symbol":"ransel_x99_frame_trampoline"} */
void mod_ransel_x99_frame_update(void)
{
    ((void (*)(void))(void *)ransel_x99_frame_trampoline)();
}

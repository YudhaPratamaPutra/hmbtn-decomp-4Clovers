/* Diag E: access game_state.globalFlags in hook (guard only), then trampoline */
#include <sys/types.h>
#include "types.h"
#include "farm_shared.h"
#include "player.h"
#include "picture_cells.h"
#include "mips_auto_hook.h"

MIPS_AUTO_HOOK_TRAMPOLINE(ransel_x99_frame_trampoline);

/* MIPS_AUTO_HOOK: {"id":"ransel-x99-frame-update","type":"hook","site_symbol":"player_frame_update","trampoline_symbol":"ransel_x99_frame_trampoline"} */
void mod_ransel_x99_frame_update(void)
{
    if ((game_state.globalFlags & (GLOBAL_FLAG_PAUSED | GLOBAL_FLAG_MENU_OPEN | GLOBAL_FLAG_TRANSITION)) == 0)
    {
        /* no-op */
    }
    ((void (*)(void))(void *)ransel_x99_frame_trampoline)();
}

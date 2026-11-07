/* Hook TU: passthrough only (no ransel function definitions here) */
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
    ((void (*)(void))(void *)ransel_x99_frame_trampoline)();
}

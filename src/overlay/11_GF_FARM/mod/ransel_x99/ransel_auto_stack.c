/* Ransel X99 - DIAGNOSTIC PASSTHROUGH
 * Sementara: hook hanya meneruskan eksekusi ke body asli player_frame_update
 * lewat trampoline, TANPA logika ransel. Dipakai untuk isolasi penyebab freeze.
 */
#include "types.h"
#include "mips_auto_hook.h"

MIPS_AUTO_HOOK_TRAMPOLINE(ransel_x99_frame_trampoline);

/* MIPS_AUTO_HOOK: {"id":"ransel-x99-frame-update","type":"hook","site_symbol":"player_frame_update","trampoline_symbol":"ransel_x99_frame_trampoline"} */
void mod_ransel_x99_frame_update(void)
{
    ((void (*)(void))(void *)ransel_x99_frame_trampoline)();
}

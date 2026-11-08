
/*
 * FARM stamina/fatigue HUD.
 * Draws current and maximum values on two rows.
 */

#include <sys/types.h>
#include <libgte.h>

#include "types.h"
#include "clock.h"
#include "farm_state.h"
#include "main.h"
#include "window_frame.h"
#include "text.h"
#include "text_bank.h"
#include "ui_icons.h"
#include "prim.h"

static void farm_hud_draw_fatigue_icon(u_long *ot, s16 x, s16 y)
{
    prim_add_line(ot, x + 4, y,     x + 1, y + 4, 0x509CFF, 0);
    prim_add_line(ot, x + 4, y,     x + 7, y + 4, 0x509CFF, 0);
    prim_add_line(ot, x + 1, y + 4, x + 2, y + 7, 0x509CFF, 0);
    prim_add_line(ot, x + 2, y + 7, x + 6, y + 7, 0x509CFF, 0);
    prim_add_line(ot, x + 6, y + 7, x + 7, y + 4, 0x509CFF, 0);
}

/*
 * Keep the custom stamina/fatigue panel in step with the game's clock panel.
 * The stock clock panel is suppressed while the clock is pending or a menu
 * is open, and otherwise follows the saved status-latch option. The generic
 * menu window also uses menuState; not every quantity/message prompt sets
 * GLOBAL_FLAG_MENU_OPEN.
 */
static s32 farm_hud_clock_panel_visible(void)
{
    if (clock_is_pending() == 1) {
        return 0;
    }
    if (game_state.globalFlags & GLOBAL_FLAG_MENU_OPEN) {
        return 0;
    }
    if (game_state.system.menuState != MENU_STATE_IDLE) {
        return 0;
    }
    return game_state.world.options.statusLatch != 0;
}

void panel_stamina_draw(void)
{
    u_long *content_ot;

    if (current_frame == 0 || !farm_hud_clock_panel_visible()) {
        return;
    }

    /* Panel background and contents use separate OT slots. */
    window_frame_draw(&current_frame->otTags[0][31],
                      8, 16, 90, 32);

    content_ot = &current_frame->otTags[0][30];

    /* Row 1: current stamina / maximum stamina. */
    ui_draw_icon_2a(content_ot, 16, 23);
    text_draw_number(game_state.player.stamina, -1,
                     content_ot, 30, 21);
    text_draw_plain(content_ot,
                    LOCALIZED(text_bank.messages.slash),
                    55, 21);
    text_draw_number(game_state.player.maxStamina, -1,
                     content_ot, 65, 21);

    /* Row 2: current fatigue / maximum fatigue (100). */
    farm_hud_draw_fatigue_icon(content_ot, 16, 34);
    text_draw_number(game_state.player.fatigue, -1,
                     content_ot, 30, 33);
    text_draw_plain(content_ot,
                    LOCALIZED(text_bank.messages.slash),
                    55, 33);
    text_draw_number(100, -1, content_ot, 65, 33);

}

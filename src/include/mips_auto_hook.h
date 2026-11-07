#ifndef MIPS_AUTO_HOOK_H
#define MIPS_AUTO_HOOK_H

#include "types.h"

/*
 * Declares a 16-byte (4-word) trampoline storage buffer in the overlay's
 * .mips_trampoline.<overlay> section. The linker script brackets this section
 * with __mips_trampoline_start_<overlay> and __mips_trampoline_end_<overlay>.
 *
 * The hook-register tool resolves this symbol from the linker map, derives its
 * file offset from the explicit image base, reads the 16-byte trampoline guard,
 * and writes the displaced-instruction trampoline there. The integration
 * planner validates that the trampoline falls entirely between the start and
 * end symbols before applying any patch.
 *
 * Usage (placed at file scope, typically near the top of the mod source):
 *
 *     #include "mips_auto_hook.h"
 *     MIPS_AUTO_HOOK_TRAMPOLINE(ransel_x99_trampoline);
 *
 * Then declare a hook immediately above a function definition:
 *
 *     /* MIPS_AUTO_HOOK: {"id":"my-hook","type":"hook",
 *      *   "site_symbol":"farm_some_function",
 *      *   "trampoline_symbol":"ransel_x99_trampoline"} */
 *     s32 mod_my_hook(...) { ... }
 */
#define MIPS_AUTO_HOOK_TRAMPOLINE(sym) \
    __attribute__((section(".mips_trampoline.11_GF_FARM"), aligned(4), used)) \
    u32 sym[4] = {0, 0, 0, 0}

#endif /* MIPS_AUTO_HOOK_H */
#ifndef MIPS_AUTO_HOOK_H
#define MIPS_AUTO_HOOK_H

#include "types.h"

/*
 * Declares a 16-byte (4-word) trampoline storage buffer.
 *
 * The hook-register tool resolves this symbol from the linker map,
 * derives its file offset from the explicit image base, reads the
 * 16-byte trampoline guard, and writes the displaced-instruction
 * trampoline there.
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
    u32 sym[4] = {0, 0, 0, 0}

#endif /* MIPS_AUTO_HOOK_H */
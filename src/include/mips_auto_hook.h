#ifndef MIPS_AUTO_HOOK_H
#define MIPS_AUTO_HOOK_H

#include "types.h"

/*
 * Reserve one 16-byte (4-word) trampoline slot in the overlay's
 * linker-owned .mips_trampoline section. The hook-register tool resolves
 * this symbol from the linker map, derives its file offset from the
 * explicit image base, reads the 16-byte trampoline guard, and writes the
 * displaced-instruction trampoline there.
 *
 * The symbol name must match trampoline_symbol in the MIPS_AUTO_HOOK
 * declaration comment. The section attribute is what keeps the slot inside
 * the KEEP(*(.mips_trampoline.@NAME@)) range that overlay.ld.in brackets
 * between __mips_trampoline_start_ and __mips_trampoline_end_; without it
 * the array lands in .data and registration rejects it.
 */
#define MIPS_AUTO_HOOK_TRAMPOLINE(symbol) \
    unsigned int symbol[4] \
        __attribute__((section(".mips_trampoline.11_GF_FARM"), aligned(4))) = {0, 0, 0, 0}

#endif /* MIPS_AUTO_HOOK_H */

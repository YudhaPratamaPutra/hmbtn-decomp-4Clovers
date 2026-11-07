#ifndef MIPS_AUTO_HOOK_H
#define MIPS_AUTO_HOOK_H
  
/*
 * Reserve one 16-byte trampoline slot in the overlay's linker-owned section.
 * The symbol name must match trampoline_symbol in the MIPS_AUTO_HOOK comment.
 */

#define MIPS_AUTO_HOOK_TRAMPOLINE(symbol) \
    unsigned int symbol[4] \
        __attribute__((section(".mips_trampoline.11_GF_FARM"), aligned(4))) = {0, 0, 0, 0}

#endif

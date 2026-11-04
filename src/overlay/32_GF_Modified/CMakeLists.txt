# 32_GF_Modified, an overlay (32_GF_Modified.bin in A_FILE). The source list is in link order.

psx_overlay(32_GF_Modified FILE 32_GF_Modified.bin REGION low OWN_COMMONS
    SOURCES
    item_stack_mod.c
    ransel_stack_mod.c
    
    # Filler the linker leaves in the alignment gap after a file's .data,
    # which no object holds.
    #Gap

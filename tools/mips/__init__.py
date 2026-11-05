"""MIPS-I/R3000 instruction, JAL, and HOOK utilities."""
from .core import Instruction, MipsDecodeError, decode, encode_i, encode_j, encode_r
from .jal import (
    JalCallsite, JalEngineError, JalPatch, apply_jal_patches,
    patches_to_json, plan_jal_patch, scan_jal,
)
from .hook import (
    HookEngineError, HookPatchPlan, apply_hook_patch,
    hook_plan_to_json, plan_hook_patch,
)
from .discovery import ModDiscoveryError, ModInventory, discover_mod_sources
from .integration import IntegrationError, IntegrationPlan, build_integration_plan, apply_integration_plan
from .validation import ValidationError, ValidationReport, validate_integrated_image\nfrom .symbols import (
    SymbolDefinition, SymbolResolution, SymbolResolverError,
    load_linker_map, parse_linker_map, resolve_symbol, resolve_symbols,
)

__all__ = [
    "Instruction", "MipsDecodeError", "decode", "encode_i", "encode_j", "encode_r",
    "JalCallsite", "JalEngineError", "JalPatch", "scan_jal",
    "plan_jal_patch", "apply_jal_patches", "patches_to_json",
    "HookEngineError", "HookPatchPlan", "plan_hook_patch",
    "apply_hook_patch", "hook_plan_to_json",
    "ModDiscoveryError", "ModInventory", "discover_mod_sources",
    "SymbolDefinition", "SymbolResolution", "SymbolResolverError",
    "load_linker_map", "parse_linker_map", "resolve_symbol", "resolve_symbols",
    "IntegrationError", "IntegrationPlan", "build_integration_plan", "apply_integration_plan",\n    "ValidationError", "ValidationReport", "validate_integrated_image",
]

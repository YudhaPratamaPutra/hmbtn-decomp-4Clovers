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

__all__ = [
    "Instruction", "MipsDecodeError", "decode", "encode_i", "encode_j", "encode_r",
    "JalCallsite", "JalEngineError", "JalPatch", "scan_jal",
    "plan_jal_patch", "apply_jal_patches", "patches_to_json",
    "HookEngineError", "HookPatchPlan", "plan_hook_patch",
    "apply_hook_patch", "hook_plan_to_json",
]

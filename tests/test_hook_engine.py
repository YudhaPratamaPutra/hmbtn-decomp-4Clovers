import struct
import unittest

from tools.mips.hook import (
    HookEngineError, apply_hook_patch, plan_hook_patch,
)


class HookEngineTests(unittest.TestCase):
    def setUp(self):
        self.base = 0x80010000
        self.site_offset = 0x10
        self.trampoline_offset = 0x40
        self.original = (0x27BDFFE8, 0xAFBF0010)
        self.expected_trampoline = b"\xCC" * 16
        self.image = bytearray(b"\xAA" * 0x80)
        struct.pack_into("<2I", self.image, self.site_offset, *self.original)
        self.image[self.trampoline_offset:self.trampoline_offset + 16] = self.expected_trampoline

    def plan(self, **overrides):
        args = dict(
            site_offset=self.site_offset,
            site_pc=self.base + self.site_offset,
            hook_pc=0x80024000,
            trampoline_offset=self.trampoline_offset,
            trampoline_pc=0x80030000,
            expected_original_words=self.original,
            expected_trampoline=self.expected_trampoline,
        )
        args.update(overrides)
        return plan_hook_patch(bytes(self.image), **args)

    def test_plan_and_apply_writes_hook_and_trampoline(self):
        plan = self.plan()
        patched = apply_hook_patch(bytes(self.image), plan)
        self.assertEqual(len(patched), len(self.image))
        self.assertEqual(struct.unpack_from("<2I", patched, self.site_offset), plan.hook_words)
        self.assertEqual(struct.unpack_from("<4I", patched, self.trampoline_offset),
                         plan.trampoline_words)
        self.assertEqual(bytes(self.image), bytes(self.image))

    def test_hook_site_original_guard(self):
        with self.assertRaises(HookEngineError):
            self.plan(expected_original_words=(0, 0))

    def test_trampoline_storage_guard(self):
        with self.assertRaises(HookEngineError):
            self.plan(expected_trampoline=b"\0" * 16)

    def test_reject_control_transfer_in_displaced_pair(self):
        with self.assertRaises(HookEngineError):
            self.plan(expected_original_words=(0x10000001, 0))

    def test_reject_unknown_instruction_in_displaced_pair(self):
        with self.assertRaises(HookEngineError):
            self.plan(expected_original_words=(0xFFFFFFFF, 0))

    def test_reject_overlapping_storage(self):
        with self.assertRaises(HookEngineError):
            self.plan(trampoline_offset=self.site_offset + 4)

    def test_reject_trampoline_outside_image(self):
        with self.assertRaises(HookEngineError):
            self.plan(trampoline_offset=0x7C)

    def test_reject_hook_outside_jump_region(self):
        with self.assertRaises(HookEngineError):
            self.plan(hook_pc=0x90000000)

    def test_apply_rechecks_originals(self):
        plan = self.plan()
        changed = bytearray(self.image)
        struct.pack_into("<I", changed, self.site_offset, 0)
        with self.assertRaises(HookEngineError):
            apply_hook_patch(bytes(changed), plan)

    def test_apply_rechecks_trampoline_storage(self):
        plan = self.plan()
        changed = bytearray(self.image)
        changed[self.trampoline_offset] ^= 0xFF
        with self.assertRaises(HookEngineError):
            apply_hook_patch(bytes(changed), plan)


if __name__ == "__main__":
    unittest.main()

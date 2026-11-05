import unittest

from tools.mips.hook import HookEngineError, plan_hook_patch


class HookInputTypeTests(unittest.TestCase):
    def _plan(self, **overrides):
        args = {
            "site_offset": 0,
            "site_pc": 0x80010000,
            "hook_pc": 0x80011000,
            "trampoline_offset": 32,
            "trampoline_pc": 0x80010020,
            "expected_original_words": (0, 0),
            "expected_trampoline": b"\x00" * 16,
        }
        args.update(overrides)
        return plan_hook_patch(b"\x00" * 64, **args)

    def test_rejects_boolean_addresses(self):
        for field in ("site_pc", "hook_pc", "trampoline_pc"):
            with self.subTest(field=field):
                with self.assertRaises(HookEngineError):
                    self._plan(**{field: False})

    def test_rejects_boolean_file_offsets(self):
        for field in ("site_offset", "trampoline_offset"):
            with self.subTest(field=field):
                with self.assertRaises(HookEngineError):
                    self._plan(**{field: False})


if __name__ == "__main__":
    unittest.main()

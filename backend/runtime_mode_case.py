from types import SimpleNamespace
import unittest


class RuntimeModeTestCase(unittest.TestCase):
    def test_packaged_sidecar_defaults_to_desktop_mode(self):
        from backend.runtime_mode import resolve_runtime_mode

        mode = resolve_runtime_mode(
            env={},
            sys_module=SimpleNamespace(
                frozen=True,
                executable=r"C:\Program Files\Discord Marketing Desktop\backend-api.exe",
            ),
        )

        self.assertTrue(mode.desktop_single_user)
        self.assertTrue(mode.desktop_skip_ai_warmup)
        self.assertFalse(mode.license_required)
        self.assertEqual(mode.desktop_mode_source, "packaged-backend-default")

    def test_explicit_env_overrides_packaged_defaults(self):
        from backend.runtime_mode import resolve_runtime_mode

        mode = resolve_runtime_mode(
            env={
                "DESKTOP_SINGLE_USER": "0",
                "DESKTOP_SKIP_AI_WARMUP": "0",
                "LICENSE_REQUIRED": "1",
            },
            sys_module=SimpleNamespace(
                frozen=True,
                executable=r"C:\Program Files\Discord Marketing Desktop\backend-api.exe",
            ),
        )

        self.assertFalse(mode.desktop_single_user)
        self.assertFalse(mode.desktop_skip_ai_warmup)
        self.assertTrue(mode.license_required)
        self.assertEqual(mode.desktop_mode_source, "env")


if __name__ == "__main__":
    unittest.main()

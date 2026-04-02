import unittest

from backend import optional_image_support


class _FakeLogger:
    def __init__(self):
        self.info_messages = []
        self.warning_messages = []

    def info(self, message):
        self.info_messages.append(message)

    def warning(self, message):
        self.warning_messages.append(message)


class _FakePiHeifModule:
    def __init__(self):
        self.called = 0

    def register_heif_opener(self):
        self.called += 1


class OptionalImageSupportTestCase(unittest.TestCase):
    def setUp(self):
        optional_image_support.reset_optional_image_plugin_state_for_tests()

    def tearDown(self):
        optional_image_support.reset_optional_image_plugin_state_for_tests()

    def test_missing_pi_heif_is_allowed(self):
        fake_logger = _FakeLogger()

        def importer(_name):
            raise ModuleNotFoundError("No module named 'pi_heif'")

        enabled = optional_image_support.enable_optional_pillow_image_plugins(
            import_module=importer,
            log=fake_logger,
        )

        self.assertFalse(enabled)
        self.assertEqual(fake_logger.warning_messages, [])
        self.assertEqual(fake_logger.info_messages, ["未安装 pi-heif，跳过 HEIC/HEIF 图片支持"])

    def test_pi_heif_is_registered_when_available(self):
        fake_logger = _FakeLogger()
        fake_module = _FakePiHeifModule()

        enabled = optional_image_support.enable_optional_pillow_image_plugins(
            import_module=lambda _name: fake_module,
            log=fake_logger,
        )

        self.assertTrue(enabled)
        self.assertEqual(fake_module.called, 1)
        self.assertEqual(fake_logger.warning_messages, [])
        self.assertEqual(fake_logger.info_messages, ["已启用 HEIC/HEIF 图片支持"])


if __name__ == "__main__":
    unittest.main()

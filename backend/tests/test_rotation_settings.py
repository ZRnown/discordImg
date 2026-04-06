import unittest

from backend.rotation_settings import resolve_rotation_settings_update


class RotationSettingsTestCase(unittest.TestCase):
    def test_accepts_keyword_match_limit_during_mode_switch(self):
        result = resolve_rotation_settings_update(
            current_settings={
                "rotation_interval": 180,
                "rotation_enabled": 1,
                "reply_mode": "rotation",
                "keyword_reply_interval": 180,
                "keyword_reply_batch_size": 0,
                "keyword_batch_dispatch_mode": "immediate",
            },
            sender_count=1,
            reply_mode="default",
            keyword_match_limit=2,
        )

        self.assertEqual(result["reply_mode"], "default")
        self.assertEqual(result["rotation_enabled"], 0)

    def test_all_mode_allows_zero_interval_for_multiple_senders(self):
        result = resolve_rotation_settings_update(
            current_settings={
                "rotation_interval": 180,
                "rotation_enabled": 1,
                "reply_mode": "rotation",
                "keyword_reply_interval": 180,
                "keyword_reply_batch_size": 0,
                "keyword_batch_dispatch_mode": "immediate",
            },
            sender_count=5,
            reply_mode="all",
            rotation_interval=0,
        )

        self.assertEqual(result["reply_mode"], "all")
        self.assertEqual(result["rotation_enabled"], 0)
        self.assertEqual(result["rotation_interval"], 0)


if __name__ == "__main__":
    unittest.main()

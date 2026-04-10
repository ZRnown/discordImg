import importlib
import importlib.util
import unittest
from types import SimpleNamespace


def _load_watchdog_module(test_case: unittest.TestCase):
    spec = importlib.util.find_spec("backend.bot_watchdog")
    test_case.assertIsNotNone(spec, "backend.bot_watchdog should exist")
    return importlib.import_module("backend.bot_watchdog")


class BotWatchdogCandidateTestCase(unittest.TestCase):
    def test_missing_runtime_account_is_selected_for_restart(self):
        module = _load_watchdog_module(self)

        candidates = module.collect_watchdog_restart_candidates(
            [{"id": 42, "username": "oopbuy_listener"}],
            {},
            now_monotonic=120.0,
            restart_attempt_timestamps={},
            min_restart_interval_seconds=30.0,
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["account"]["id"], 42)
        self.assertEqual(candidates[0]["reason"], "missing_runtime")

    def test_closed_client_is_selected_for_restart(self):
        module = _load_watchdog_module(self)

        runtime_entries = {
            42: {
                "client": SimpleNamespace(account_id=42, is_closed=lambda: True),
                "task": SimpleNamespace(done=lambda: False),
                "index": 0,
            }
        }

        candidates = module.collect_watchdog_restart_candidates(
            [{"id": 42, "username": "oopbuy_listener"}],
            runtime_entries,
            now_monotonic=120.0,
            restart_attempt_timestamps={},
            min_restart_interval_seconds=30.0,
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["reason"], "client_closed")

    def test_running_client_is_not_selected_for_restart(self):
        module = _load_watchdog_module(self)

        runtime_entries = {
            42: {
                "client": SimpleNamespace(account_id=42, is_closed=lambda: False),
                "task": SimpleNamespace(done=lambda: False),
                "index": 0,
            }
        }

        candidates = module.collect_watchdog_restart_candidates(
            [{"id": 42, "username": "oopbuy_listener"}],
            runtime_entries,
            now_monotonic=120.0,
            restart_attempt_timestamps={},
            min_restart_interval_seconds=30.0,
        )

        self.assertEqual(candidates, [])

    def test_restart_cooldown_blocks_immediate_repeat_attempt(self):
        module = _load_watchdog_module(self)

        candidates = module.collect_watchdog_restart_candidates(
            [{"id": 42, "username": "oopbuy_listener"}],
            {},
            now_monotonic=120.0,
            restart_attempt_timestamps={42: 105.0},
            min_restart_interval_seconds=30.0,
        )

        self.assertEqual(candidates, [])

    def test_stalled_disconnected_client_is_selected_for_restart(self):
        module = _load_watchdog_module(self)

        runtime_entries = {
            42: {
                "client": SimpleNamespace(
                    account_id=42,
                    is_closed=lambda: False,
                    is_ready=lambda: False,
                    last_disconnect_at=100.0,
                    last_ready_at=80.0,
                ),
                "task": SimpleNamespace(done=lambda: False),
                "index": 0,
            }
        }

        candidates = module.collect_watchdog_restart_candidates(
            [{"id": 42, "username": "oopbuy_listener"}],
            runtime_entries,
            now_monotonic=120.0,
            restart_attempt_timestamps={},
            min_restart_interval_seconds=30.0,
            disconnected_grace_seconds=8.0,
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["reason"], "disconnected_stalled")

    def test_initial_login_without_disconnect_is_not_selected_for_restart(self):
        module = _load_watchdog_module(self)

        runtime_entries = {
            42: {
                "client": SimpleNamespace(
                    account_id=42,
                    is_closed=lambda: False,
                    is_ready=lambda: False,
                    last_disconnect_at=0.0,
                    last_ready_at=0.0,
                ),
                "task": SimpleNamespace(done=lambda: False),
                "index": 0,
            }
        }

        candidates = module.collect_watchdog_restart_candidates(
            [{"id": 42, "username": "oopbuy_listener"}],
            runtime_entries,
            now_monotonic=120.0,
            restart_attempt_timestamps={},
            min_restart_interval_seconds=30.0,
            disconnected_grace_seconds=8.0,
        )

        self.assertEqual(candidates, [])


if __name__ == "__main__":
    unittest.main()

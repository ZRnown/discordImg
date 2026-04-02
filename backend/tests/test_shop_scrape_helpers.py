import threading
import unittest

from backend import shop_scrape_helpers


class ShopScrapeHelpersTestCase(unittest.TestCase):
    def test_build_weidian_shop_api_headers_uses_shop_page_referer(self):
        headers = shop_scrape_helpers.build_weidian_shop_api_headers("1834000157")

        self.assertEqual(
            headers["Referer"],
            "https://weidian.com/?userid=1834000157&tabType=all",
        )
        self.assertEqual(headers["Origin"], "https://weidian.com")
        self.assertEqual(headers["X-Requested-With"], "XMLHttpRequest")
        self.assertIn("application/json", headers["Accept"])

    def test_reset_scrape_stop_event_clears_stale_stop_state(self):
        stop_event = threading.Event()
        stop_event.set()

        shop_scrape_helpers.reset_scrape_stop_event(stop_event)

        self.assertFalse(stop_event.is_set())

    def test_clear_stale_scrape_stop_state_resets_idle_stop_flag_and_event(self):
        if not hasattr(shop_scrape_helpers, "clear_stale_scrape_stop_state"):
            self.fail("clear_stale_scrape_stop_state is missing")

        stop_event = threading.Event()
        stop_event.set()
        updates = []

        def update_status(**kwargs):
            updates.append(kwargs)
            return True

        cleared = shop_scrape_helpers.clear_stale_scrape_stop_state(
            {
                "is_scraping": False,
                "stop_signal": True,
                "completed": True,
                "message": "正在等待当前商品完成...",
            },
            stop_event,
            update_status,
        )

        self.assertTrue(cleared)
        self.assertFalse(stop_event.is_set())
        self.assertEqual(
            updates,
            [
                {
                    "stop_signal": False,
                    "completed": False,
                    "message": "等待开始...",
                }
            ],
        )

    def test_clear_stale_scrape_stop_state_keeps_active_stop_request(self):
        if not hasattr(shop_scrape_helpers, "clear_stale_scrape_stop_state"):
            self.fail("clear_stale_scrape_stop_state is missing")

        stop_event = threading.Event()
        stop_event.set()
        updates = []

        cleared = shop_scrape_helpers.clear_stale_scrape_stop_state(
            {
                "is_scraping": True,
                "stop_signal": True,
                "completed": False,
                "message": "正在停止抓取...",
            },
            stop_event,
            lambda **kwargs: updates.append(kwargs),
        )

        self.assertFalse(cleared)
        self.assertTrue(stop_event.is_set())
        self.assertEqual(updates, [])


if __name__ == "__main__":
    unittest.main()

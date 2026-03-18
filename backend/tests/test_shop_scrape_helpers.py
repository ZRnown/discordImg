import threading
import unittest

from backend.shop_scrape_helpers import (
    build_weidian_shop_api_headers,
    reset_scrape_stop_event,
)


class ShopScrapeHelpersTestCase(unittest.TestCase):
    def test_build_weidian_shop_api_headers_uses_shop_page_referer(self):
        headers = build_weidian_shop_api_headers("1834000157")

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

        reset_scrape_stop_event(stop_event)

        self.assertFalse(stop_event.is_set())


if __name__ == "__main__":
    unittest.main()

import threading
from typing import Dict


def build_weidian_shop_api_headers(shop_id: str) -> Dict[str, str]:
    normalized_shop_id = str(shop_id or "").strip()
    referer = "https://weidian.com/"
    if normalized_shop_id:
        referer = f"https://weidian.com/?userid={normalized_shop_id}&tabType=all"

    return {
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://weidian.com",
        "Referer": referer,
        "X-Requested-With": "XMLHttpRequest",
    }


def reset_scrape_stop_event(stop_event: threading.Event) -> None:
    if stop_event is not None:
        stop_event.clear()

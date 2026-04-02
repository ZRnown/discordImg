import threading
from typing import Callable, Dict, Optional


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


def clear_stale_scrape_stop_state(
    current_status: Optional[Dict],
    stop_event: Optional[threading.Event],
    update_status: Optional[Callable[..., bool]] = None,
) -> bool:
    status = current_status or {}
    is_idle = not bool(status.get("is_scraping"))
    has_stale_stop_state = bool(status.get("stop_signal")) or bool(
        stop_event is not None and stop_event.is_set()
    )

    if not is_idle or not has_stale_stop_state:
        return False

    if update_status is not None:
        updated = update_status(
            stop_signal=False,
            completed=False,
            message="等待开始...",
        )
        if updated is False:
            return False

    reset_scrape_stop_event(stop_event)
    return True

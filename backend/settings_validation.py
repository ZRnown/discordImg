from __future__ import annotations

REPLY_DELAY_MIN = 0.1
REPLY_DELAY_MAX = 300.0
REPLY_DELAY_STEP = 0.1


def _round_delay(value: float) -> float:
    return round(float(value), 1)


def normalize_reply_delay_range(min_delay: float, max_delay: float) -> tuple[float, float]:
    normalized_min = _round_delay(min(max(float(min_delay), REPLY_DELAY_MIN), REPLY_DELAY_MAX - REPLY_DELAY_STEP))
    normalized_max = _round_delay(min(max(float(max_delay), normalized_min + REPLY_DELAY_STEP), REPLY_DELAY_MAX))
    return normalized_min, normalized_max


def validate_reply_delay_range(min_delay: float, max_delay: float) -> str | None:
    if min_delay < 0 or max_delay < 0:
        return "延迟时间不能为负数"
    if min_delay >= max_delay:
        return "最小延迟必须小于最大延迟"
    if max_delay > 300:
        return "最大延迟不能超过300秒"
    return None

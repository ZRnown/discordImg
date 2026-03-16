from typing import Any, Dict


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_interval(value: Any, default: int) -> int:
    interval = _coerce_int(value, default)
    return interval if interval > 0 else default


def _normalize_rotation_enabled(value: Any, default: int = 1) -> int:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"0", "false", "no", "off"}:
            return 0
        if normalized in {"1", "true", "yes", "on"}:
            return 1
        return default
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        return 1 if int(value) else 0
    return default


def _normalize_reply_mode(value: Any, default: str = "rotation") -> str:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"default", "rotation", "keyword"}:
            return normalized
    return default


def _normalize_batch_size(value: Any, default: int = 0) -> int:
    batch_size = _coerce_int(value, default)
    return max(0, batch_size)


def resolve_rotation_settings_update(
    current_settings: Dict[str, Any],
    sender_count: int,
    rotation_interval: int = None,
    rotation_enabled: int = None,
    keyword_reply_interval: int = None,
    keyword_reply_batch_size: int = None,
    reply_mode: str = None,
) -> Dict[str, int]:
    base_rotation_interval = _normalize_interval(
        (current_settings or {}).get("rotation_interval"),
        180,
    )
    effective_rotation_interval = _normalize_interval(
        rotation_interval,
        base_rotation_interval,
    )

    base_keyword_interval = _normalize_interval(
        (current_settings or {}).get("keyword_reply_interval"),
        base_rotation_interval,
    )
    effective_keyword_interval = _normalize_interval(
        keyword_reply_interval,
        base_keyword_interval if keyword_reply_interval is None else effective_rotation_interval,
    )

    base_batch_size = _normalize_batch_size(
        (current_settings or {}).get("keyword_reply_batch_size"),
        0,
    )
    effective_batch_size = _normalize_batch_size(
        keyword_reply_batch_size,
        base_batch_size,
    )

    base_rotation_enabled = _normalize_rotation_enabled(
        (current_settings or {}).get("rotation_enabled"),
        1,
    )
    effective_rotation_enabled = _normalize_rotation_enabled(
        rotation_enabled,
        base_rotation_enabled,
    )
    base_reply_mode = _normalize_reply_mode(
        (current_settings or {}).get("reply_mode"),
        "keyword"
        if base_rotation_enabled == 0 and base_batch_size > 0
        else "rotation",
    )
    requested_reply_mode = _normalize_reply_mode(reply_mode, base_reply_mode)

    has_keyword_update = (
        keyword_reply_interval is not None
        or keyword_reply_batch_size is not None
    )
    if sender_count != 1 and has_keyword_update:
        raise ValueError("仅绑定1个发送账号时可设置单轮关键词时间和上限")

    if sender_count != 1 and reply_mode is not None and requested_reply_mode == "keyword":
        raise ValueError("仅绑定1个发送账号时可切换到关键词模式")

    effective_reply_mode = requested_reply_mode
    if sender_count != 1 and effective_reply_mode == "keyword":
        effective_reply_mode = "rotation"

    if effective_reply_mode == "keyword":
        effective_rotation_enabled = 0
    elif effective_reply_mode == "default":
        effective_rotation_enabled = 0
    elif reply_mode is not None:
        effective_rotation_enabled = 1

    return {
        "rotation_interval": effective_rotation_interval,
        "rotation_enabled": effective_rotation_enabled,
        "keyword_reply_interval": effective_keyword_interval,
        "keyword_reply_batch_size": effective_batch_size,
        "reply_mode": effective_reply_mode,
    }

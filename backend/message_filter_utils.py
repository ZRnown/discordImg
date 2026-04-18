import json
import re
from typing import Any, Callable


def split_filter_values(raw_value: Any) -> list[str]:
    if raw_value is None:
        return []
    if isinstance(raw_value, (list, tuple, set)):
        values: list[str] = []
        for item in raw_value:
            values.extend(split_filter_values(item))
        return values

    normalized = str(raw_value).replace("，", ",").replace("\n", ",")
    return [item.strip() for item in normalized.split(",") if item and item.strip()]


def get_keyword_match_limit_from_filters(filters: list[dict[str, Any]] | None) -> int | None:
    positive_limits: list[int] = []
    has_unlimited_rule = False

    for rule in filters or []:
        if (rule or {}).get("filter_type") != "keyword_match_limit":
            continue

        try:
            limit = int((rule or {}).get("filter_value"))
        except (TypeError, ValueError):
            continue

        if limit < 0:
            continue
        if limit == 0:
            has_unlimited_rule = True
            continue
        positive_limits.append(limit)

    if positive_limits:
        return min(positive_limits)
    if has_unlimited_rule:
        return 0
    return None


def resolve_keyword_match_limit(
    filters: list[dict[str, Any]] | None,
    fallback_limit: int | None = None,
) -> int | None:
    filter_limit = get_keyword_match_limit_from_filters(filters)
    if filter_limit is None:
        return fallback_limit
    return filter_limit


def has_filter_type(
    filters: list[dict[str, Any]] | None,
    filter_type: str,
) -> bool:
    target = str(filter_type or "").strip()
    if not target:
        return False
    return any((rule or {}).get("filter_type") == target for rule in (filters or []))


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def should_run_ocr_for_image_reply(
    website_configs: list[dict[str, Any]] | None,
    website_filters_map: dict[int, list[dict[str, Any]]] | None,
    *,
    global_filters: list[dict[str, Any]] | None = None,
    similarity: Any,
    base_threshold: Any,
) -> bool:
    normalized_similarity = _coerce_float(similarity)
    if normalized_similarity is None:
        return False

    normalized_base_threshold = _coerce_float(base_threshold)
    if normalized_base_threshold is None:
        normalized_base_threshold = 0.0

    if has_filter_type(global_filters, "ocr_contains") and normalized_similarity >= normalized_base_threshold:
        return True

    filters_map = website_filters_map or {}
    for website_config in website_configs or []:
        website_id = website_config.get("id")
        if website_id is None:
            continue

        website_filters = filters_map.get(int(website_id)) or []
        if not has_filter_type(website_filters, "ocr_contains"):
            continue

        website_threshold = _coerce_float((website_config or {}).get("image_similarity_threshold"))
        threshold_to_use = website_threshold if website_threshold is not None else normalized_base_threshold
        if normalized_similarity >= threshold_to_use:
            return True

    return False


def filters_block_message(
    message: Any,
    filters: list[dict[str, Any]] | None,
    match_context: dict[str, Any] | None = None,
    message_has_image: Callable[[Any], bool] | None = None,
) -> bool:
    message_content = (getattr(message, "content", "") or "").lower()
    has_image = message_has_image or (lambda _message: False)

    for filter_rule in filters or []:
        raw_filter_value = (filter_rule or {}).get("filter_value") or ""
        filter_value = str(raw_filter_value).lower()
        filter_type = (filter_rule or {}).get("filter_type")

        if filter_type == "contains":
            if filter_value in message_content:
                return True
        elif filter_type == "starts_with":
            if message_content.startswith(filter_value):
                return True
        elif filter_type == "ends_with":
            if message_content.endswith(filter_value):
                return True
        elif filter_type == "regex":
            try:
                if re.search(filter_value, message_content, re.IGNORECASE):
                    return True
            except re.error:
                continue
        elif filter_type == "numeric_range":
            try:
                rule = json.loads(raw_filter_value) if raw_filter_value else {}
            except json.JSONDecodeError:
                rule = {}

            keyword = str(rule.get("keyword") or "").strip()
            min_value = rule.get("min")
            max_value = rule.get("max")

            if not keyword:
                continue

            try:
                min_value = int(min_value)
                max_value = int(max_value)
            except (TypeError, ValueError):
                continue

            if min_value >= max_value:
                continue

            pattern = rf"(?i){re.escape(keyword)}\s*[:=-]?\s*(\d+)"
            value_matches = re.findall(pattern, getattr(message, "content", "") or "")
            for value_str in value_matches:
                try:
                    value = int(value_str)
                except ValueError:
                    continue
                if value < min_value or value > max_value:
                    return True
        elif filter_type == "user_id":
            filter_user_ids = split_filter_values(filter_value)
            sender_id = str(getattr(getattr(message, "author", None), "id", ""))
            sender_name = str(getattr(getattr(message, "author", None), "name", "")).lower()
            for blocked_id in filter_user_ids:
                if blocked_id == sender_id or blocked_id.lower() in sender_name:
                    return True
        elif filter_type == "role_id":
            role_ids = set(split_filter_values(filter_value))
            if role_ids and getattr(message, "guild", None):
                author_roles = getattr(getattr(message, "author", None), "roles", []) or []
                author_role_ids = {
                    str(role.id)
                    for role in author_roles
                    if getattr(role, "id", None) is not None
                }
                if author_role_ids.intersection(role_ids):
                    return True
        elif filter_type == "image":
            if has_image(message):
                return True
        elif filter_type == "image_similarity":
            if not match_context or match_context.get("type") != "image":
                continue
            try:
                threshold = float(raw_filter_value)
            except (TypeError, ValueError):
                continue
            similarity = match_context.get("similarity", 0)
            try:
                similarity = float(similarity)
            except (TypeError, ValueError):
                similarity = 0
            if similarity >= threshold:
                return True
        elif filter_type == "ocr_contains":
            if not match_context or match_context.get("type") != "image":
                continue
            ocr_text = str(match_context.get("ocr_text") or "").lower()
            if not ocr_text:
                continue
            for keyword in split_filter_values(filter_value):
                if keyword and keyword in ocr_text:
                    return True

    return False

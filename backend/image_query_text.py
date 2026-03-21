import re


def build_image_query_text(message) -> str:
    raw_text = getattr(message, "clean_content", None) or getattr(message, "content", None) or ""
    normalized = re.sub(r"\s+", " ", str(raw_text)).strip()
    return normalized[:200]

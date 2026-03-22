import re
from typing import Any


def normalize_keyword_search_text(value: str) -> str:
    if not value:
        return ""
    value = re.sub(r"[\u200b-\u200d\uFEFF]", "", str(value))
    value = value.lower()
    value = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def tokenize_keyword_search_text(normalized_text: str) -> list[str]:
    if not normalized_text:
        return []
    return re.findall(r"[a-z0-9\u4e00-\u9fff]+", normalized_text)


def _query_has_alpha_context(tokens: list[str]) -> bool:
    return any(not token.isdigit() for token in tokens)


def _should_include_standalone_numeric_token(tokens: list[str]) -> bool:
    # Mixed alpha+number queries like "b 30" should stay bound to the model code.
    # Otherwise standalone numbers become extremely noisy and match unrelated items.
    return not _query_has_alpha_context(tokens)


def build_query_keyword_candidates(value: str) -> dict[str, str]:
    normalized_text = normalize_keyword_search_text(value)
    candidates: dict[str, str] = {}
    tokens = tokenize_keyword_search_text(normalized_text)
    include_numeric_token = _should_include_standalone_numeric_token(tokens)

    def add(raw_value: str, display_value: str | None = None):
        normalized = normalize_keyword_search_text(raw_value)
        canonical = re.sub(r"\s+", "", normalized)
        if len(canonical) < 2:
            return
        candidates.setdefault(canonical, (display_value or normalized or canonical).strip())

    if normalized_text and len(tokens) <= 3:
        add(normalized_text, normalized_text)

    for token in tokens:
        if token.isdigit():
            if include_numeric_token:
                add(token, token)
            continue
        if len(token) >= 2:
            add(token, token)

    for size in (2, 3):
        if len(tokens) < size:
            continue
        for idx in range(len(tokens) - size + 1):
            part_tokens = tokens[idx: idx + size]
            compact = "".join(part_tokens)
            if len(compact) < 2:
                continue
            if any(ch.isdigit() for ch in compact):
                add(compact, compact)

    return candidates


def build_product_keyword_variants(raw_value: str) -> set[str]:
    normalized_text = normalize_keyword_search_text(raw_value)
    variants: set[str] = set()
    tokens = tokenize_keyword_search_text(normalized_text)

    def add(raw_text: str):
        normalized = normalize_keyword_search_text(raw_text)
        canonical = re.sub(r"\s+", "", normalized)
        if len(canonical) < 2:
            return
        variants.add(canonical)

    if normalized_text:
        add(normalized_text)

    for token in tokens:
        if len(token) >= 2 or token.isdigit():
            add(token)

    for size in (2, 3):
        if len(tokens) < size:
            continue
        for idx in range(len(tokens) - size + 1):
            compact = "".join(tokens[idx: idx + size])
            if len(compact) < 2:
                continue
            if any(ch.isdigit() for ch in compact):
                add(compact)

    return variants


def build_text_search_plan(query: Any) -> dict[str, list[str] | str]:
    query_normalized = normalize_keyword_search_text(query)
    tokens = tokenize_keyword_search_text(query_normalized)
    include_numeric_token = _should_include_standalone_numeric_token(tokens)

    numeric_terms: list[str] = []
    if tokens:
        seen_numeric = set()
        for idx, token in enumerate(tokens):
            if not any(ch.isdigit() for ch in token):
                continue
            if idx - 1 >= 0:
                phrase = f"{tokens[idx - 1]} {token}"
                if phrase not in seen_numeric:
                    numeric_terms.append(phrase)
                    seen_numeric.add(phrase)
            if idx - 2 >= 0:
                phrase = f"{tokens[idx - 2]} {tokens[idx - 1]} {token}"
                if phrase not in seen_numeric:
                    numeric_terms.append(phrase)
                    seen_numeric.add(phrase)

    extra_terms: list[str] = []
    if len(tokens) >= 2:
        for i in range(len(tokens) - 1):
            term = f"{tokens[i]} {tokens[i + 1]}"
            if term not in extra_terms:
                extra_terms.append(term)

    if include_numeric_token:
        for token in tokens:
            if any(ch.isdigit() for ch in token) and len(token) >= 2 and token not in extra_terms:
                extra_terms.append(token)

    fallback_tokens: list[str] = []
    for token in tokens:
        if token.isdigit():
            if include_numeric_token:
                fallback_tokens.append(token)
            continue
        if len(token) >= 2:
            fallback_tokens.append(token)

    return {
        "query_normalized": query_normalized,
        "numeric_terms": numeric_terms,
        "extra_terms": extra_terms,
        "fallback_tokens": fallback_tokens,
    }

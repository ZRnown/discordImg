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


def _is_split_numeric_only_query(tokens: list[str]) -> bool:
    return len(tokens) > 1 and all(token.isdigit() for token in tokens)


def _should_include_standalone_numeric_token(tokens: list[str]) -> bool:
    # Mixed alpha+number queries like "b 30" should stay bound to the model code.
    # Otherwise standalone numbers become extremely noisy and match unrelated items.
    if _is_split_numeric_only_query(tokens):
        return False
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

    if normalized_text and len(tokens) <= 3 and not _is_split_numeric_only_query(tokens):
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
            if all(token.isdigit() for token in part_tokens):
                continue
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
    allow_alpha_token_variants = len(tokens) == 1

    def add(raw_text: str):
        normalized = normalize_keyword_search_text(raw_text)
        canonical = re.sub(r"\s+", "", normalized)
        if len(canonical) < 2:
            return
        variants.add(canonical)

    if normalized_text:
        add(normalized_text)

    for token in tokens:
        if any(ch.isdigit() for ch in token):
            add(token)
            continue
        if allow_alpha_token_variants and len(token) >= 2:
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


def split_keyword_phrases(raw_value: Any) -> list[str]:
    if not raw_value:
        return []

    if isinstance(raw_value, list):
        parts: list[str] = []
        for item in raw_value:
            parts.extend(re.split(r"[,\uFF0C]", str(item)))
    else:
        parts = re.split(r"[,\uFF0C]", str(raw_value))

    phrases: list[str] = []
    for part in parts:
        normalized = normalize_keyword_search_text(part)
        canonical = re.sub(r"\s+", "", normalized)
        if canonical and len(canonical) >= 2:
            phrases.append(normalized)
    return phrases


def find_query_keyword_match(
    query_keyword_candidates: dict[str, str],
    english_title: Any = None,
    title: str | None = None,
) -> dict[str, str] | None:
    if not query_keyword_candidates:
        return None

    query_keyword_keys = set(query_keyword_candidates.keys())

    def match_phrases(phrases: list[str], source: str) -> dict[str, str] | None:
        seen = set()
        for phrase in phrases:
            if phrase in seen:
                continue
            seen.add(phrase)
            product_variants = build_product_keyword_variants(phrase)
            matched_keywords = sorted(
                query_keyword_keys.intersection(product_variants),
                key=lambda value: (-len(value), value),
            )
            if matched_keywords:
                matched_keyword = matched_keywords[0]
                return {
                    "phrase": query_keyword_candidates.get(matched_keyword, matched_keyword),
                    "source": source,
                    "rule": "canonical_keyword_match",
                    "canonical_keyword": matched_keyword,
                }
        return None

    english_phrases = split_keyword_phrases(english_title)
    matched = match_phrases(english_phrases, "english_title")
    if matched:
        return matched

    if not english_phrases:
        normalized_title = normalize_keyword_search_text(title or "")
        canonical_title = re.sub(r"\s+", "", normalized_title)
        if canonical_title and len(canonical_title) >= 2:
            return match_phrases([normalized_title], "title")

    return None


def build_text_search_plan(query: Any) -> dict[str, list[str] | str]:
    query_normalized = normalize_keyword_search_text(query)
    tokens = tokenize_keyword_search_text(query_normalized)
    include_numeric_token = _should_include_standalone_numeric_token(tokens)

    numeric_terms: list[str] = []
    if tokens and not _is_split_numeric_only_query(tokens):
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
    if len(tokens) >= 2 and not _is_split_numeric_only_query(tokens):
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

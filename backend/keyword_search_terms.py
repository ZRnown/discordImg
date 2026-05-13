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


def normalize_partition_match_rules(raw_value: Any) -> list[list[str]]:
    parsed = raw_value
    if isinstance(raw_value, str):
        text = raw_value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return []

    if not isinstance(parsed, list):
        return []

    normalized: list[list[str]] = []
    for row in parsed:
        if isinstance(row, (list, tuple)):
            cells = [str(cell).strip() if cell is not None else "" for cell in row]
        else:
            cells = [str(row).strip() if row is not None else ""]

        if any(cells):
            normalized.append(cells)

    return normalized


def serialize_partition_match_rules(raw_value: Any) -> str:
    return json.dumps(normalize_partition_match_rules(raw_value), ensure_ascii=False)


def _build_partition_query_text(
    query_keyword_candidates: dict[str, str],
    query_text: Any = None,
) -> str:
    direct_query = normalize_keyword_search_text(str(query_text or ""))
    if direct_query:
        return direct_query

    if not query_keyword_candidates:
        return ""

    combined = " ".join(
        str(display or "").strip()
        for display in query_keyword_candidates.values()
        if str(display or "").strip()
    )
    return normalize_keyword_search_text(combined)


def _partition_token_matches_query(token: str, query_tokens: list[str]) -> bool:
    if not token:
        return True

    if token in query_tokens:
        return True

    if token.isdigit():
        return any(
            query_token == token
            or (
                any(ch.isdigit() for ch in query_token)
                and (query_token.endswith(token) or token in query_token)
            )
            for query_token in query_tokens
        )

    if len(token) == 1 and token.isalpha():
        return any(
            query_token.startswith(token) and any(ch.isdigit() for ch in query_token)
            for query_token in query_tokens
        )

    return any(
        query_token == token
        or query_token.startswith(token)
        for query_token in query_tokens
    )


def _partition_cell_matches_query(cell: str, query_tokens: list[str], query_compact: str) -> bool:
    normalized_cell = normalize_keyword_search_text(cell)
    if not normalized_cell:
        return True

    cell_tokens = tokenize_keyword_search_text(normalized_cell)
    cell_compact = re.sub(r"\s+", "", normalized_cell)
    if len(cell_tokens) > 1 and cell_compact and cell_compact in query_compact:
        return True

    if not cell_tokens:
        return cell_compact in query_compact

    return all(_partition_token_matches_query(token, query_tokens) for token in cell_tokens)


def find_partition_keyword_match(
    query_keyword_candidates: dict[str, str],
    partition_match_rules: Any = None,
    *,
    query_text: Any = None,
) -> dict[str, str] | None:
    rules = normalize_partition_match_rules(partition_match_rules)
    if not rules:
        return None

    normalized_query = _build_partition_query_text(
        query_keyword_candidates,
        query_text=query_text,
    )
    if not normalized_query:
        return None

    query_tokens = tokenize_keyword_search_text(normalized_query)
    query_compact = re.sub(r"\s+", "", normalized_query)
    if not query_tokens and not query_compact:
        return None

    for row_index, row in enumerate(rules):
        active_cells = [str(cell or "").strip() for cell in row if str(cell or "").strip()]
        if not active_cells:
            continue
        if all(_partition_cell_matches_query(cell, query_tokens, query_compact) for cell in active_cells):
            canonical = "&".join(
                re.sub(r"\s+", "", normalize_keyword_search_text(cell))
                for cell in active_cells
            )
            return {
                "phrase": " + ".join(active_cells),
                "source": f"partition_row:{row_index}",
                "rule": "partition_keyword_match",
                "canonical_keyword": canonical or f"partition_row_{row_index}",
            }

    return None


def _normalize_allowed_languages(value: Any) -> set[str] | None:
    if value is None:
        return None

    parsed: list[Any]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return set()
        try:
            loaded = json.loads(text)
        except json.JSONDecodeError:
            parsed = [part.strip() for part in text.replace('，', ',').split(',')]
        else:
            if isinstance(loaded, list):
                parsed = loaded
            elif isinstance(loaded, str):
                parsed = [loaded]
            else:
                parsed = [text]
    elif isinstance(value, (list, tuple, set)):
        parsed = list(value)
    else:
        parsed = [value]

    normalized = set()
    for item in parsed:
        language = str(item or '').strip().lower()
        if language in SUPPORTED_KEYWORD_LANGUAGES:
            normalized.add(language)
    return normalized


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

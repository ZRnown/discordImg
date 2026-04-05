import json
import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
NON_WORD_RE = re.compile(r"[\W_]+", re.UNICODE)
SUPPORTED_KEYWORD_LANGUAGES = {'zh', 'en', 'pt', 'es', 'fr', 'de', 'ru', 'ja', 'ko'}


def normalize_keyword_search_text(value: str) -> str:
    if not value:
        return ""
    value = re.sub(r"[\u200b-\u200d\uFEFF]", "", str(value))
    value = value.lower()
    value = NON_WORD_RE.sub(" ", value)
    return re.sub(r"\s+", " ", value).strip()


def tokenize_keyword_search_text(normalized_text: str) -> list[str]:
    if not normalized_text:
        return []
    return WORD_RE.findall(normalized_text)


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

    for size in (2, 3):
        if len(tokens) < size:
            continue
        for idx in range(len(tokens) - size + 1):
            part_tokens = tokens[idx: idx + size]
            if all(token.isdigit() for token in part_tokens):
                continue
            phrase = " ".join(part_tokens)
            compact = "".join(part_tokens)
            if len(compact) < 2:
                continue
            add(phrase, phrase)

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
        if any(ch.isdigit() for ch in token):
            add(token)
            continue

    for size in (2, 3):
        if len(tokens) < size:
            continue
        for idx in range(len(tokens) - size + 1):
            part_tokens = tokens[idx: idx + size]
            compact = "".join(part_tokens)
            if len(compact) < 2:
                continue
            if any(any(ch.isdigit() for ch in token) for token in part_tokens):
                add(" ".join(part_tokens))

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
    title_translations: Any = None,
    allowed_languages: Any = None,
) -> dict[str, str] | None:
    if not query_keyword_candidates:
        return None

    query_keyword_keys = set(query_keyword_candidates.keys())
    allowed_language_set = _normalize_allowed_languages(allowed_languages)

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

    if allowed_language_set is None or 'en' in allowed_language_set:
        english_phrases = split_keyword_phrases(english_title)
        matched = match_phrases(english_phrases, "english_title")
        if matched:
            return matched

    parsed_translations = {}
    if isinstance(title_translations, str):
        try:
            parsed = json.loads(title_translations)
            if isinstance(parsed, dict):
                parsed_translations = parsed
        except json.JSONDecodeError:
            parsed_translations = {}
    elif isinstance(title_translations, dict):
        parsed_translations = title_translations

    for language, translated_title in parsed_translations.items():
        normalized_language = str(language or '').strip().lower()
        if allowed_language_set is not None and normalized_language not in allowed_language_set:
            continue
        matched = match_phrases(
            split_keyword_phrases(translated_title),
            f"title_translation:{normalized_language}",
        )
        if matched:
            return matched

    if allowed_language_set is None or 'zh' in allowed_language_set:
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
        if query_normalized:
            extra_terms.append(query_normalized)
        for size in (2, 3):
            if len(tokens) < size or size == len(tokens):
                continue
            for i in range(len(tokens) - size + 1):
                term = " ".join(tokens[i: i + size])
                if term not in extra_terms:
                    extra_terms.append(term)

    if include_numeric_token and len(tokens) == 1:
        for token in tokens:
            if any(ch.isdigit() for ch in token) and len(token) >= 2 and token not in extra_terms:
                extra_terms.append(token)

    fallback_tokens: list[str] = []
    if len(tokens) == 1:
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


def _extract_urls_from_text(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    urls = re.findall(r"https?://[^\s<>'\"]+", text, flags=re.IGNORECASE)
    return urls or [text]


def _iter_decoded_texts(value: str, max_rounds: int = 4) -> list[str]:
    variants: list[str] = []
    current = value
    for _ in range(max_rounds + 1):
        if current not in variants:
            variants.append(current)
        decoded = unquote(current)
        if decoded == current:
            break
        current = decoded
    return variants


def extract_marketplace_item_id_from_text(value: Any) -> str | None:
    for raw_candidate in _extract_urls_from_text(value):
        for candidate in _iter_decoded_texts(raw_candidate):
            direct_item_match = re.search(r"itemID=(\d+)", candidate, flags=re.IGNORECASE)
            if direct_item_match:
                return direct_item_match.group(1)

            path_match = re.search(
                r"/(?:product/weidian|goods/weidian)/(\d+)",
                candidate,
                flags=re.IGNORECASE,
            )
            if path_match:
                return path_match.group(1)

            parsed = urlparse(candidate)
            host = (parsed.netloc or "").lower()
            query_params = parse_qs(parsed.query)
            direct_id = (query_params.get("id") or [None])[0]
            if direct_id and str(direct_id).isdigit():
                source = ((query_params.get("source") or [""])[0]).lower()
                platform = ((query_params.get("platform") or [""])[0]).lower()
                if (
                    source == "wd"
                    or platform == "weidian"
                    or "acbuy.com" in host
                    or "cnfans.com" in host
                ):
                    return str(direct_id)

    return None

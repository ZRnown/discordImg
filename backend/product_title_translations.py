import json
import logging
from typing import Any, Callable, Dict, Iterable, List

import requests


logger = logging.getLogger(__name__)

SUPPORTED_TITLE_LANGUAGES = (
    'zh',
    'en',
    'pt',
    'es',
    'fr',
    'de',
    'ru',
    'ja',
    'ko',
)
TRANSLATABLE_TITLE_LANGUAGES = tuple(
    language for language in SUPPORTED_TITLE_LANGUAGES if language != 'zh'
)
DEFAULT_ENABLED_TITLE_LANGUAGES = ('en',)
DEFAULT_REPLY_LANGUAGES = ('en',)
DEFAULT_REPLY_LANGUAGE = 'link_only'
LANGUAGE_AWARE_DEFAULT_TEMPLATE = '{title}\n{url}'
TITLE_JOIN_SEPARATOR = ' / '


def _coerce_text(value: Any) -> str:
    if value is None:
        return ''
    return str(value).strip()


def _parse_language_values(raw_value: Any) -> List[Any] | None:
    if raw_value is None:
        return None

    if isinstance(raw_value, str):
        text = raw_value.strip()
        if not text:
            return []
        if text.lower() in {'none', 'null', 'link_only'}:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, str):
            return [parsed]
        return [part.strip() for part in text.replace('，', ',').split(',')]

    if isinstance(raw_value, (list, tuple, set)):
        return list(raw_value)

    return [raw_value]


def normalize_reply_language(value: Any) -> str:
    normalized = str(value or DEFAULT_REPLY_LANGUAGE).strip().lower()
    if normalized in {'none', 'null'}:
        normalized = DEFAULT_REPLY_LANGUAGE
    if normalized == DEFAULT_REPLY_LANGUAGE:
        return DEFAULT_REPLY_LANGUAGE
    return normalized if normalized in SUPPORTED_TITLE_LANGUAGES else DEFAULT_REPLY_LANGUAGE


def normalize_enabled_title_languages(value: Any) -> List[str]:
    parsed = _parse_language_values(value)
    normalized: List[str] = ['en']
    seen = {'en'}

    if parsed is None:
        return normalized

    for item in parsed:
        language = _coerce_text(item).lower()
        if language not in TRANSLATABLE_TITLE_LANGUAGES or language in seen:
            continue
        if language == 'en':
            continue
        normalized.append(language)
        seen.add(language)

    return normalized


def normalize_reply_languages(
    value: Any,
    legacy_reply_language: Any = None,
) -> List[str]:
    parsed = _parse_language_values(value)
    if parsed is None:
        legacy = normalize_reply_language(legacy_reply_language)
        if legacy_reply_language is not None:
            return [] if legacy == DEFAULT_REPLY_LANGUAGE else [legacy]
        return list(DEFAULT_REPLY_LANGUAGES)

    normalized: List[str] = []
    seen = set()
    for item in parsed:
        language = normalize_reply_language(item)
        if language == DEFAULT_REPLY_LANGUAGE or language in seen:
            continue
        normalized.append(language)
        seen.add(language)
    return normalized


def get_effective_reply_languages(
    value: Any,
    legacy_reply_language: Any = None,
) -> List[str]:
    normalized = normalize_reply_languages(
        value,
        legacy_reply_language=legacy_reply_language,
    )
    return normalized or list(DEFAULT_REPLY_LANGUAGES)


def serialize_enabled_title_languages(value: Any) -> str:
    return json.dumps(normalize_enabled_title_languages(value), ensure_ascii=False)


def serialize_reply_languages(
    value: Any,
    legacy_reply_language: Any = None,
) -> str:
    return json.dumps(
        normalize_reply_languages(value, legacy_reply_language=legacy_reply_language),
        ensure_ascii=False,
    )


def normalize_title_translations(
    raw_value: Any,
    *,
    title: Any = '',
    english_title: Any = '',
) -> Dict[str, str]:
    if isinstance(raw_value, str):
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError:
            parsed = {}
    elif isinstance(raw_value, dict):
        parsed = raw_value
    else:
        parsed = {}

    normalized: Dict[str, str] = {}
    for language, value in parsed.items():
        key = str(language or '').strip().lower()
        if key not in SUPPORTED_TITLE_LANGUAGES:
            continue
        text = _coerce_text(value)
        if text:
            normalized[key] = text

    title_text = _coerce_text(title)
    english_text = _coerce_text(english_title)
    if title_text and not normalized.get('zh'):
        normalized['zh'] = title_text
    if english_text and not normalized.get('en'):
        normalized['en'] = english_text
    return normalized


def serialize_title_translations(
    raw_value: Any,
    *,
    title: Any = '',
    english_title: Any = '',
) -> str:
    normalized = normalize_title_translations(
        raw_value,
        title=title,
        english_title=english_title,
    )
    return json.dumps(normalized, ensure_ascii=False)


def _resolve_product_translations(product: Any) -> Dict[str, str]:
    product_dict = product if isinstance(product, dict) else {}
    return normalize_title_translations(
        product_dict.get('titleTranslations') or product_dict.get('title_translations'),
        title=product_dict.get('title'),
        english_title=product_dict.get('englishTitle') or product_dict.get('english_title'),
    )


def get_localized_product_titles(
    product: Any,
    reply_languages: Any = None,
    *,
    reply_language: Any = None,
) -> List[str]:
    translations = _resolve_product_translations(product)
    preferred_languages = get_effective_reply_languages(
        reply_languages if reply_languages is not None else reply_language,
        legacy_reply_language=reply_language if reply_languages is not None else None,
    )

    titles: List[str] = []
    seen = set()
    fallback = (
        translations.get('en')
        or translations.get('zh')
        or _coerce_text((product or {}).get('englishTitle') if isinstance(product, dict) else '')
        or _coerce_text((product or {}).get('english_title') if isinstance(product, dict) else '')
        or _coerce_text((product or {}).get('title') if isinstance(product, dict) else '')
    )

    for language in preferred_languages:
        title = (
            translations.get(language)
            or translations.get('en')
            or translations.get('zh')
            or fallback
        )
        if title and title not in seen:
            titles.append(title)
            seen.add(title)

    if not titles and fallback:
        titles.append(fallback)
    return titles


def get_localized_product_title(
    product: Any,
    reply_language: Any = DEFAULT_REPLY_LANGUAGE,
    *,
    reply_languages: Any = None,
) -> str:
    return TITLE_JOIN_SEPARATOR.join(
        get_localized_product_titles(
            product,
            reply_languages=reply_languages,
            reply_language=reply_language,
        )
    )


def get_reply_title_value(
    product: Any,
    reply_languages: Any = None,
    *,
    reply_language: Any = None,
) -> str:
    return get_localized_product_title(
        product,
        reply_language=reply_language,
        reply_languages=reply_languages,
    )


def render_reply_template(
    template: Any,
    response_url: Any,
    product: Any,
    reply_language: Any = DEFAULT_REPLY_LANGUAGE,
    *,
    reply_languages: Any = None,
) -> str:
    template_text = _coerce_text(template)
    if not template_text:
        return ''

    product_dict = product if isinstance(product, dict) else {}
    translations = _resolve_product_translations(product_dict)

    placeholder_values = {
        'url': _coerce_text(response_url),
        'title': get_reply_title_value(
            product_dict,
            reply_languages=reply_languages,
            reply_language=reply_language,
        ),
    }
    for language in SUPPORTED_TITLE_LANGUAGES:
        fallback_title = (
            translations.get(language)
            or translations.get('en')
            or translations.get('zh')
            or ''
        )
        placeholder_values[f'title_{language}'] = fallback_title

    rendered = template_text
    for placeholder, value in placeholder_values.items():
        rendered = rendered.replace(f'{{{placeholder}}}', value)
    return rendered.strip()


def apply_reply_language_template_default(
    template: Any,
    reply_language: Any = DEFAULT_REPLY_LANGUAGE,
    *,
    reply_languages: Any = None,
) -> str:
    normalized_template = _coerce_text(template) or '{url}'
    if reply_languages is not None:
        active_reply_languages = normalize_reply_languages(
            reply_languages,
            legacy_reply_language=reply_language,
        )
        if not active_reply_languages and normalized_template == LANGUAGE_AWARE_DEFAULT_TEMPLATE:
            return '{url}'
        return normalized_template

    active_reply_languages = normalize_reply_languages(
        reply_language,
    )
    if not active_reply_languages:
        if normalized_template == LANGUAGE_AWARE_DEFAULT_TEMPLATE:
            return '{url}'
        return normalized_template
    if normalized_template == '{url}':
        return LANGUAGE_AWARE_DEFAULT_TEMPLATE
    return normalized_template


def translate_title_with_google(text: Any, target_language: str) -> str:
    text_value = _coerce_text(text)
    normalized_target = _coerce_text(target_language).lower()
    if not text_value or normalized_target not in TRANSLATABLE_TITLE_LANGUAGES:
        return ''

    try:
        response = requests.get(
            'https://translate.googleapis.com/translate_a/single',
            params={
                'client': 'gtx',
                'sl': 'zh-CN',
                'tl': normalized_target,
                'dt': 't',
                'q': text_value[:500],
            },
            timeout=10,
            proxies={'http': None, 'https': None},
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list) and data and isinstance(data[0], list):
            translated = ''.join(
                str(chunk[0]).strip()
                for chunk in data[0]
                if isinstance(chunk, list) and chunk and _coerce_text(chunk[0])
            ).strip()
            return translated
    except Exception as exc:
        logger.warning(
            "Google 标题翻译失败: target=%s error=%s",
            normalized_target,
            exc,
        )
    return ''


def fill_missing_title_translations(
    raw_value: Any,
    *,
    title: Any = '',
    english_title: Any = '',
    enabled_languages: Any = None,
    translator: Callable[[str, str], str] | None = None,
) -> Dict[str, str]:
    normalized = normalize_title_translations(
        raw_value,
        title=title,
        english_title=english_title,
    )
    chinese_title = normalized.get('zh') or _coerce_text(title)
    if not chinese_title:
        return normalized

    translate = translator or translate_title_with_google
    for language in normalize_enabled_title_languages(enabled_languages):
        if normalized.get(language):
            continue
        try:
            translated = _coerce_text(translate(chinese_title, language))
        except Exception as exc:
            logger.warning(
                "标题翻译器异常: language=%s error=%s",
                language,
                exc,
            )
            translated = ''
        if translated:
            normalized[language] = translated

    return normalized


def iter_unique_translation_languages(*language_groups: Iterable[str]) -> List[str]:
    result: List[str] = []
    seen = set()
    for group in language_groups:
        for language in group:
            normalized = _coerce_text(language).lower()
            if normalized not in TRANSLATABLE_TITLE_LANGUAGES or normalized in seen:
                continue
            result.append(normalized)
            seen.add(normalized)
    return result

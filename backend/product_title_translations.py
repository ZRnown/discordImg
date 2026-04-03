import json
from typing import Any, Dict


SUPPORTED_TITLE_LANGUAGES = (
    'zh',
    'en',
    'es',
    'fr',
    'de',
    'ru',
    'ja',
    'ko',
)

DEFAULT_REPLY_LANGUAGE = 'link_only'
LANGUAGE_AWARE_DEFAULT_TEMPLATE = '{title}\n{url}'


def normalize_reply_language(value: Any) -> str:
    normalized = str(value or DEFAULT_REPLY_LANGUAGE).strip().lower()
    if normalized == 'none':
        normalized = DEFAULT_REPLY_LANGUAGE
    if normalized == DEFAULT_REPLY_LANGUAGE:
        return DEFAULT_REPLY_LANGUAGE
    return normalized if normalized in SUPPORTED_TITLE_LANGUAGES else DEFAULT_REPLY_LANGUAGE


def _coerce_text(value: Any) -> str:
    if value is None:
        return ''
    return str(value).strip()


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


def get_localized_product_title(product: Any, reply_language: Any = DEFAULT_REPLY_LANGUAGE) -> str:
    product_dict = product if isinstance(product, dict) else {}
    normalized_language = normalize_reply_language(reply_language)
    preferred_language = 'en' if normalized_language == DEFAULT_REPLY_LANGUAGE else normalized_language
    translations = normalize_title_translations(
        product_dict.get('titleTranslations') or product_dict.get('title_translations'),
        title=product_dict.get('title'),
        english_title=product_dict.get('englishTitle') or product_dict.get('english_title'),
    )
    return (
        translations.get(preferred_language)
        or translations.get('en')
        or translations.get('zh')
        or _coerce_text(product_dict.get('englishTitle') or product_dict.get('english_title'))
        or _coerce_text(product_dict.get('title'))
    )


def render_reply_template(
    template: Any,
    response_url: Any,
    product: Any,
    reply_language: Any = DEFAULT_REPLY_LANGUAGE,
) -> str:
    template_text = _coerce_text(template)
    if not template_text:
        return ''

    product_dict = product if isinstance(product, dict) else {}
    translations = normalize_title_translations(
        product_dict.get('titleTranslations') or product_dict.get('title_translations'),
        title=product_dict.get('title'),
        english_title=product_dict.get('englishTitle') or product_dict.get('english_title'),
    )

    placeholder_values = {
        'url': _coerce_text(response_url),
        'title': get_localized_product_title(product_dict, reply_language),
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


def apply_reply_language_template_default(template: Any, reply_language: Any) -> str:
    normalized_template = _coerce_text(template) or '{url}'
    normalized_language = normalize_reply_language(reply_language)
    if normalized_language == DEFAULT_REPLY_LANGUAGE:
        if normalized_template == LANGUAGE_AWARE_DEFAULT_TEMPLATE:
            return '{url}'
        return normalized_template
    if normalized_template == '{url}':
        return LANGUAGE_AWARE_DEFAULT_TEMPLATE
    return normalized_template

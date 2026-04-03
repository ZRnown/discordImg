import json
from typing import Any, Dict


DEFAULT_REPLY_SETTING = {
    'customReplyText': '',
    'imageSource': 'product',
    'selectedImageIndexes': [],
    'customImageUrls': [],
    'uploadedReplyImages': [],
}


def _coerce_list(value: Any) -> list:
    if value in (None, '', False):
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _coerce_text(value: Any) -> str:
    if value is None:
        return ''
    return str(value)


def _normalize_image_source(value: Any) -> str:
    normalized = str(value or 'product').strip().lower()
    if normalized in {'product', 'upload', 'custom'}:
        return normalized
    return 'product'


def _extract_uploaded_filenames(value: Any) -> list:
    filenames = []
    for item in _coerce_list(value):
        if item is None:
            continue
        text = str(item).strip()
        if not text:
            continue
        if '/' in text:
            text = text.rsplit('/', 1)[-1]
        filenames.append(text)
    return filenames


def normalize_reply_setting_entry(entry: Any) -> Dict[str, Any]:
    if not isinstance(entry, dict):
        entry = {}

    uploaded_reply_images = entry.get('uploadedReplyImages')
    if uploaded_reply_images is None:
        uploaded_reply_images = entry.get('uploaded_reply_images')
    if uploaded_reply_images is None:
        uploaded_reply_images = entry.get('existingUploadedImageUrls')
    if uploaded_reply_images is None:
        uploaded_reply_images = entry.get('uploadedImages')

    return {
        'customReplyText': _coerce_text(
            entry.get('customReplyText', entry.get('custom_reply_text', ''))
        ),
        'imageSource': _normalize_image_source(
            entry.get('imageSource', entry.get('image_source', 'product'))
        ),
        'selectedImageIndexes': _coerce_list(
            entry.get(
                'selectedImageIndexes',
                entry.get('selected_image_indexes', entry.get('custom_reply_images')),
            )
        ),
        'customImageUrls': _coerce_list(
            entry.get('customImageUrls', entry.get('custom_image_urls'))
        ),
        'uploadedReplyImages': _extract_uploaded_filenames(uploaded_reply_images),
    }


def has_reply_setting_customization(entry: Any) -> bool:
    normalized = normalize_reply_setting_entry(entry)
    if normalized['customReplyText'].strip():
        return True
    if normalized['selectedImageIndexes']:
        return True
    if normalized['customImageUrls']:
        return True
    if normalized['uploadedReplyImages']:
        return True
    return False


def parse_per_website_reply_settings(raw_settings: Any) -> Dict[str, Dict[str, Any]]:
    if not raw_settings:
        return {}

    if isinstance(raw_settings, str):
        try:
            parsed = json.loads(raw_settings)
        except json.JSONDecodeError:
            return {}
    elif isinstance(raw_settings, dict):
        parsed = raw_settings
    else:
        return {}

    normalized: Dict[str, Dict[str, Any]] = {}
    for website_id, entry in parsed.items():
        normalized[str(website_id)] = normalize_reply_setting_entry(entry)
    return normalized


def serialize_per_website_reply_settings(settings: Any) -> str:
    normalized = parse_per_website_reply_settings(settings)
    return json.dumps(normalized, ensure_ascii=False)


def resolve_effective_product_reply_settings(product: Any, website_config: Any = None) -> Dict[str, Any]:
    product_dict = product if isinstance(product, dict) else {}
    global_settings = normalize_reply_setting_entry(product_dict)
    per_website_settings = parse_per_website_reply_settings(
        product_dict.get('perWebsiteReplySettings')
        or product_dict.get('per_website_reply_settings')
    )

    website_id = None
    if isinstance(website_config, dict):
        raw_website_id = website_config.get('id')
        if raw_website_id is not None:
            website_id = str(raw_website_id)

    if website_id:
        website_entry = per_website_settings.get(website_id)
        if website_entry and has_reply_setting_customization(website_entry):
            return per_website_settings[website_id]

    return global_settings


def apply_effective_product_reply_settings(product: Any, website_config: Any = None) -> Dict[str, Any]:
    product_dict = dict(product or {})
    effective = resolve_effective_product_reply_settings(product_dict, website_config)

    product_dict['customReplyText'] = effective['customReplyText']
    product_dict['custom_reply_text'] = effective['customReplyText']
    product_dict['imageSource'] = effective['imageSource']
    product_dict['image_source'] = effective['imageSource']
    product_dict['selectedImageIndexes'] = list(effective['selectedImageIndexes'])
    product_dict['custom_reply_images'] = list(effective['selectedImageIndexes'])
    product_dict['customImageUrls'] = list(effective['customImageUrls'])
    product_dict['custom_image_urls'] = list(effective['customImageUrls'])
    product_dict['uploadedReplyImages'] = list(effective['uploadedReplyImages'])
    product_dict['uploaded_reply_images'] = list(effective['uploadedReplyImages'])
    return product_dict


def collect_uploaded_reply_filenames(product: Any) -> list[str]:
    product_dict = product if isinstance(product, dict) else {}
    filenames = []
    seen = set()

    for filename in _extract_uploaded_filenames(
        product_dict.get('uploadedReplyImages', product_dict.get('uploaded_reply_images'))
    ):
        if filename in seen:
            continue
        filenames.append(filename)
        seen.add(filename)

    per_website_settings = parse_per_website_reply_settings(
        product_dict.get('perWebsiteReplySettings')
        or product_dict.get('per_website_reply_settings')
    )
    for entry in per_website_settings.values():
        for filename in entry.get('uploadedReplyImages', []):
            if filename in seen:
                continue
            filenames.append(filename)
            seen.add(filename)

    return filenames


def build_frontend_per_website_reply_settings(raw_settings: Any, product_id: Any) -> Dict[str, Dict[str, Any]]:
    normalized = parse_per_website_reply_settings(raw_settings)
    frontend_settings: Dict[str, Dict[str, Any]] = {}
    for website_id, entry in normalized.items():
        frontend_settings[website_id] = {
            **entry,
            'uploadedImages': [
                f"/api/custom_reply_image/{product_id}/{filename}"
                for filename in entry['uploadedReplyImages']
            ],
        }
    return frontend_settings

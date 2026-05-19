from __future__ import annotations

from dataclasses import dataclass, field
from collections import OrderedDict
import hashlib
import json
import logging
import numpy as np
import os
import pickle
import re
import tempfile
from statistics import mean
from threading import Lock, Thread
from time import perf_counter
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote

from PIL import Image, ImageFilter

try:
    from .benchmarks.common import (
        _PRODUCT_RANK_SECOND_BEST_WEIGHT,
        _PRODUCT_RANK_TOP3_MEAN_WEIGHT,
        _PRODUCT_RANK_TOP5_MEAN_WEIGHT,
        aggregate_product_rankings,
        parse_bing_image_urls,
    )
except ImportError:
    from benchmarks.common import (
        _PRODUCT_RANK_SECOND_BEST_WEIGHT,
        _PRODUCT_RANK_TOP3_MEAN_WEIGHT,
        _PRODUCT_RANK_TOP5_MEAN_WEIGHT,
        aggregate_product_rankings,
        parse_bing_image_urls,
    )
try:
    from .live_search_runtime import should_enable_streaming_live_search
except ImportError:
    from live_search_runtime import should_enable_streaming_live_search

logger = logging.getLogger(__name__)

_STREAMING_PROGRESS_LOG_INTERVAL_SECONDS = 5.0
_SCOPED_CATALOG_DISK_CACHE_VERSION = 1


def _is_search_cancelled(cancel_event: Optional[Any]) -> bool:
    if cancel_event is None:
        return False

    is_set = getattr(cancel_event, "is_set", None)
    if not callable(is_set):
        return False

    try:
        return bool(is_set())
    except Exception:
        return False


class LiveCatalogPreparingError(RuntimeError):
    """Raised when the live-search catalog is still warming in the background."""


@dataclass(frozen=True)
class LiveCatalogImageRecord:
    product_id: str
    title: str
    english_title: str
    description: str
    shop_name: str
    image_path: str
    image_index: int
    product_url: str = ""
    cnfans_url: str = ""
    acbuy_url: str = ""
    rule_enabled: bool = True
    reply_scope: str = "all"
    image_source: str = "product"
    custom_reply_text: str = ""
    custom_reply_images: str = ""
    custom_image_urls: str = ""
    uploaded_reply_images: str = ""
    item_id: str = ""
    queries: List[str] = field(default_factory=list)
    image_db_id: int = 0
    cache_strategy_name: str = ""
    cache_version: str = ""
    cache_embedding: Optional[Any] = None
    cache_color_hist: Optional[Any] = None
    cache_tokens: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class LiveQueryRecord:
    image_path: str
    query: str = ""
    query_group: str = "live"
    title: str = ""
    expected_product_id: str = ""
    shop_name: str = ""
    product_queries: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class LiveProductSupportRecord:
    expected_product_id: str
    image_path: str
    title: str = ""
    product_queries: List[str] = field(default_factory=list)


_RUNTIME_SIGNATURE_ENV_PREFIXES: tuple[str, ...] = (
    "LIVE_IMAGE_SEARCH_",
    "SIGLIP2_RERANK_",
    "RETRIEVAL_PRODUCT_RANK_",
)
_AUTO_SUPPORT_VARIANT_SUFFIXES: tuple[str, ...] = (
    "center",
    "compressed",
    "perspective",
    "background",
)
_EXTERNAL_SUPPORT_METADATA_FILENAME = "metadata.json"
_RESAMPLING = getattr(Image, "Resampling", Image)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return int(default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return int(default)
    return value if value >= 0 else int(default)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return float(default)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return float(default)
    return value if value >= 0 else float(default)


def _resolve_auto_support_output_dir(raw_path: str = "") -> str:
    output_dir = str(raw_path or "").strip()
    if output_dir:
        if os.path.isabs(output_dir):
            return output_dir
        backend_dir = os.path.dirname(__file__)
        return os.path.abspath(os.path.join(backend_dir, output_dir))

    return os.path.join(os.path.dirname(__file__), "data", "live_image_support")


def _resolve_external_support_output_dir(raw_path: str = "") -> str:
    output_dir = str(raw_path or "").strip()
    if output_dir:
        if os.path.isabs(output_dir):
            return output_dir
        backend_dir = os.path.dirname(__file__)
        return os.path.abspath(os.path.join(backend_dir, output_dir))

    return os.path.join(
        os.path.dirname(__file__),
        "data",
        "live_image_external_support",
    )


def _normalize_product_support_mode(raw_mode: Any) -> str:
    value = str(raw_mode or "").strip().lower()
    if value in {"manifest", "merge", "auto"}:
        return value
    return "auto"


def _get_product_support_mode() -> str:
    return _normalize_product_support_mode(
        os.getenv("LIVE_IMAGE_SEARCH_PRODUCT_SUPPORT_MODE", "auto")
    )


def _build_runtime_env_signature(strategy_name: str) -> Tuple[Tuple[str, str], ...]:
    pairs = [("LIVE_IMAGE_SEARCH_STRATEGY_NAME", str(strategy_name or "").strip())]
    for key, value in os.environ.items():
        if any(key.startswith(prefix) for prefix in _RUNTIME_SIGNATURE_ENV_PREFIXES):
            pairs.append((str(key), str(value)))
    return tuple(sorted(pairs))


def _append_unique_values(
    target: List[str],
    values: Sequence[Any],
    *,
    limit: int = 0,
) -> List[str]:
    seen = set(target)
    max_items = max(int(limit or 0), 0)
    for raw_value in values:
        normalized = " ".join(str(raw_value or "").strip().split())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        target.append(normalized)
        if max_items > 0 and len(target) >= max_items:
            break
    return target


def _collect_unique_product_queries(records: Sequence[LiveCatalogImageRecord]) -> List[str]:
    seen: set[str] = set()
    ordered: List[str] = []
    for record in records:
        for value in list(getattr(record, "queries", []) or []):
            normalized = str(value or "").strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                ordered.append(normalized)
    return ordered


def _open_rgb_image(image_path: str) -> Optional[Image.Image]:
    try:
        with Image.open(image_path) as image:
            return image.convert("RGB")
    except Exception:
        return None


def _verify_support_image(image_path: str) -> bool:
    try:
        with Image.open(image_path) as image:
            image.verify()
        return os.path.getsize(image_path) > 256
    except Exception:
        return False


def _resolve_external_support_image_suffix(url: str) -> str:
    normalized = str(url or "").split("?", 1)[0].lower()
    match = re.search(
        r"\.(jpe?g|png|webp|bmp|gif|tiff?|heic|avif)(?:$|[^a-z0-9])",
        normalized,
    )
    if not match:
        return ".jpg"
    ext = match.group(1)
    if ext in {"jpg", "jpeg"}:
        return ".jpg"
    if ext in {"tif", "tiff"}:
        return ".tiff"
    return f".{ext}"


def build_external_product_support_queries(
    product_row: Dict[str, Any],
    *,
    max_queries: int = 4,
) -> List[str]:
    title = str(
        product_row.get("title")
        or product_row.get("name")
        or ""
    ).strip()
    english_title = str(product_row.get("english_title") or "").strip()
    item_id = str(product_row.get("item_id") or "").strip()

    queries: List[str] = []
    _append_unique_values(
        queries,
        [
            title,
            english_title,
            f"{title} {item_id}" if title and item_id else "",
            f"{english_title} {item_id}" if english_title and item_id else "",
            item_id,
        ],
        limit=max_queries,
    )
    return queries


def _fetch_bing_search_image_urls(session: Any, query: str, limit: int = 12) -> List[str]:
    response = session.get(
        "https://www.bing.com/images/search?q=" + quote(query),
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=(10, 20),
    )
    response.raise_for_status()
    return parse_bing_image_urls(response.text, limit=limit)


def _download_external_support_image(
    session: Any,
    url: str,
    out_path: str | os.PathLike[str],
) -> Optional[str]:
    resolved_path = os.fspath(out_path)
    if os.path.exists(resolved_path) and _verify_support_image(resolved_path):
        return resolved_path

    os.makedirs(os.path.dirname(resolved_path), exist_ok=True)
    try:
        response = session.get(
            url,
            timeout=(10, 20),
            headers={"User-Agent": "Mozilla/5.0"},
            stream=True,
        )
        response.raise_for_status()
        with open(resolved_path, "wb") as handle:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    handle.write(chunk)
    except Exception:
        try:
            os.remove(resolved_path)
        except OSError:
            pass
        return None

    if not _verify_support_image(resolved_path):
        try:
            os.remove(resolved_path)
        except OSError:
            pass
        return None
    return resolved_path


def _load_external_support_metadata(
    metadata_path: str | os.PathLike[str],
) -> Dict[str, Any]:
    resolved_path = os.fspath(metadata_path)
    if not resolved_path or not os.path.exists(resolved_path):
        return {}
    try:
        with open(resolved_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def load_external_product_support_records(
    catalog_records: Sequence[LiveCatalogImageRecord],
    *,
    support_dir: str | os.PathLike[str] | None = None,
) -> List[LiveProductSupportRecord]:
    if not _env_bool("LIVE_IMAGE_SEARCH_EXTERNAL_PRODUCT_SUPPORT_ENABLED", True):
        return []

    resolved_support_dir = _resolve_external_support_output_dir(
        str(
            os.fspath(support_dir)
            if support_dir is not None
            else os.getenv("LIVE_IMAGE_SEARCH_EXTERNAL_PRODUCT_SUPPORT_DIR", "")
        )
    )
    if not os.path.isdir(resolved_support_dir):
        return []

    allowed_product_ids = {
        str(record.product_id or "").strip()
        for record in catalog_records
        if str(record.product_id or "").strip()
    }
    allowed_item_ids = {
        str(record.item_id or "").strip()
        for record in catalog_records
        if str(record.item_id or "").strip()
    }
    per_product_limit = max(
        _env_int("LIVE_IMAGE_SEARCH_EXTERNAL_PRODUCT_SUPPORT_MAX_RECORDS", 4),
        1,
    )

    records: List[LiveProductSupportRecord] = []
    seen: set[tuple[str, str]] = set()
    metadata_paths: List[str] = []
    for root, _dirs, files in os.walk(resolved_support_dir):
        if _EXTERNAL_SUPPORT_METADATA_FILENAME in files:
            metadata_paths.append(os.path.join(root, _EXTERNAL_SUPPORT_METADATA_FILENAME))

    for metadata_path in sorted(metadata_paths):
        payload = _load_external_support_metadata(metadata_path)
        if not payload:
            continue

        product_id = str(
            payload.get("product_id")
            or payload.get("expected_product_id")
            or os.path.basename(os.path.dirname(metadata_path))
            or ""
        ).strip()
        item_id = str(payload.get("item_id") or "").strip()
        expected_product_id = ""
        if product_id and product_id in allowed_product_ids:
            expected_product_id = product_id
        elif item_id and item_id in allowed_item_ids:
            expected_product_id = item_id
        elif not allowed_product_ids and product_id:
            expected_product_id = product_id

        if not expected_product_id:
            continue

        metadata_dir = os.path.dirname(metadata_path)
        title = str(payload.get("title") or "")
        product_queries = list(payload.get("queries") or payload.get("product_queries") or [])
        image_entries = payload.get("images") or payload.get("support_images") or payload.get("query_images") or []
        added = 0
        for image_entry in image_entries:
            if added >= per_product_limit:
                break
            raw_image_path = ""
            if isinstance(image_entry, str):
                raw_image_path = image_entry
            elif isinstance(image_entry, dict):
                raw_image_path = str(
                    image_entry.get("path")
                    or image_entry.get("local_path")
                    or image_entry.get("image_path")
                    or ""
                )
            image_path = str(raw_image_path or "").strip()
            if not image_path:
                continue
            if not os.path.isabs(image_path):
                image_path = os.path.abspath(os.path.join(metadata_dir, image_path))
            key = (expected_product_id, image_path)
            if key in seen or not os.path.exists(image_path) or not _verify_support_image(image_path):
                continue
            seen.add(key)
            records.append(
                LiveProductSupportRecord(
                    expected_product_id=expected_product_id,
                    image_path=image_path,
                    title=title,
                    product_queries=list(product_queries),
                )
            )
            added += 1

    return records


def refresh_external_product_support_assets(
    product_row: Dict[str, Any],
    *,
    support_dir: str | os.PathLike[str] | None = None,
    session: Any = None,
    max_queries: int = 0,
    search_limit: int = 0,
    max_records: int = 0,
    per_query_limit: int = 0,
) -> Dict[str, Any]:
    product_id = str(
        product_row.get("id")
        or product_row.get("product_id")
        or ""
    ).strip()
    item_id = str(product_row.get("item_id") or "").strip()
    if not product_id:
        return {
            "product_id": "",
            "saved": 0,
            "reused": 0,
            "total_images": 0,
            "queries": [],
            "metadata_path": "",
        }

    resolved_support_dir = _resolve_external_support_output_dir(
        str(
            os.fspath(support_dir)
            if support_dir is not None
            else os.getenv("LIVE_IMAGE_SEARCH_EXTERNAL_PRODUCT_SUPPORT_DIR", "")
        )
    )
    resolved_max_queries = max(
        int(max_queries or _env_int("LIVE_IMAGE_SEARCH_EXTERNAL_PRODUCT_SUPPORT_MAX_QUERIES", 4)),
        1,
    )
    resolved_search_limit = max(
        int(search_limit or _env_int("LIVE_IMAGE_SEARCH_EXTERNAL_PRODUCT_SUPPORT_SEARCH_LIMIT", 12)),
        1,
    )
    resolved_max_records = max(
        int(max_records or _env_int("LIVE_IMAGE_SEARCH_EXTERNAL_PRODUCT_SUPPORT_MAX_RECORDS", 4)),
        1,
    )
    resolved_per_query_limit = max(
        int(per_query_limit or _env_int("LIVE_IMAGE_SEARCH_EXTERNAL_PRODUCT_SUPPORT_PER_QUERY_LIMIT", 2)),
        1,
    )
    queries = build_external_product_support_queries(
        product_row,
        max_queries=resolved_max_queries,
    )

    product_dir = os.path.join(resolved_support_dir, product_id)
    metadata_path = os.path.join(product_dir, _EXTERNAL_SUPPORT_METADATA_FILENAME)
    os.makedirs(product_dir, exist_ok=True)
    existing_payload = _load_external_support_metadata(metadata_path)

    image_entries: List[Dict[str, str]] = []
    seen_urls: set[str] = set()
    seen_paths: set[str] = set()
    reused = 0
    saved = 0

    def _append_entry(image_path: str, source_url: str, query: str) -> bool:
        normalized_path = str(image_path or "").strip()
        normalized_url = str(source_url or "").strip()
        relative_path = os.path.relpath(normalized_path, product_dir)
        if (
            not normalized_path
            or normalized_path in seen_paths
            or len(image_entries) >= resolved_max_records
            or not os.path.exists(normalized_path)
            or not _verify_support_image(normalized_path)
        ):
            return False
        seen_paths.add(normalized_path)
        if normalized_url:
            seen_urls.add(normalized_url)
        image_entries.append(
            {
                "path": relative_path,
                "source_url": normalized_url,
                "query": str(query or "").strip(),
            }
        )
        return True

    for existing_entry in list(existing_payload.get("images") or []):
        existing_path = str(
            existing_entry.get("path")
            or existing_entry.get("local_path")
            or existing_entry.get("image_path")
            or ""
        ).strip()
        if not existing_path:
            continue
        absolute_existing_path = existing_path
        if not os.path.isabs(absolute_existing_path):
            absolute_existing_path = os.path.abspath(os.path.join(product_dir, absolute_existing_path))
        if _append_entry(
            absolute_existing_path,
            str(existing_entry.get("source_url") or "").strip(),
            str(existing_entry.get("query") or "").strip(),
        ):
            reused += 1
        if len(image_entries) >= resolved_max_records:
            break

    session_created = False
    if session is None:
        import requests

        session = requests.Session()
        session.trust_env = False
        session_created = True

    try:
        if len(image_entries) < resolved_max_records:
            for query in queries:
                if len(image_entries) >= resolved_max_records:
                    break
                try:
                    query_urls = _fetch_bing_search_image_urls(
                        session,
                        query,
                        limit=resolved_search_limit,
                    )
                except Exception:
                    continue

                query_saved = 0
                for url in query_urls:
                    normalized_url = str(url or "").strip()
                    if (
                        not normalized_url
                        or normalized_url in seen_urls
                        or len(image_entries) >= resolved_max_records
                        or query_saved >= resolved_per_query_limit
                    ):
                        continue
                    suffix = _resolve_external_support_image_suffix(normalized_url)
                    out_path = os.path.join(
                        product_dir,
                        f"{hashlib.sha1(normalized_url.encode('utf-8')).hexdigest()[:16]}{suffix}",
                    )
                    saved_path = _download_external_support_image(session, normalized_url, out_path)
                    if not saved_path:
                        continue
                    if _append_entry(saved_path, normalized_url, query):
                        saved += 1
                        query_saved += 1
    finally:
        if session_created and session is not None:
            try:
                session.close()
            except Exception:
                pass

    merged_queries: List[str] = []
    _append_unique_values(
        merged_queries,
        list(queries) + list(existing_payload.get("queries") or []),
        limit=resolved_max_queries,
    )

    metadata_payload = {
        "product_id": product_id,
        "item_id": item_id,
        "title": str(product_row.get("title") or ""),
        "english_title": str(product_row.get("english_title") or ""),
        "queries": merged_queries,
        "images": image_entries,
    }
    with open(metadata_path, "w", encoding="utf-8") as handle:
        json.dump(metadata_payload, handle, ensure_ascii=False, indent=2)

    return {
        "product_id": product_id,
        "saved": saved,
        "reused": reused,
        "total_images": len(image_entries),
        "queries": merged_queries,
        "metadata_path": metadata_path,
    }


def _center_crop_image(image: Image.Image, crop_ratio: float = 0.88) -> Image.Image:
    crop_ratio = min(max(float(crop_ratio or 0.0), 0.1), 1.0)
    width, height = image.size
    crop_width = max(int(width * crop_ratio), 1)
    crop_height = max(int(height * crop_ratio), 1)
    left = max((width - crop_width) // 2, 0)
    top = max((height - crop_height) // 2, 0)
    return image.crop((left, top, left + crop_width, top + crop_height))


def _compress_image(image: Image.Image, max_side: int = 480) -> Image.Image:
    max_side = max(int(max_side or 0), 64)
    width, height = image.size
    longest_side = max(width, height)
    if longest_side <= max_side:
        return image.copy()
    scale = max_side / float(longest_side)
    resized = image.resize(
        (max(int(width * scale), 1), max(int(height * scale), 1)),
        _RESAMPLING.LANCZOS,
    )
    return resized


def _perspective_warp_image(image: Image.Image) -> Image.Image:
    width, height = image.size
    inset_x = max(width * 0.08, 2.0)
    inset_y = max(height * 0.05, 2.0)
    quad = (
        inset_x,
        inset_y,
        width - inset_x,
        0.0,
        width,
        height - inset_y,
        0.0,
        height,
    )
    return image.transform(
        (width, height),
        Image.Transform.QUAD,
        quad,
        resample=_RESAMPLING.BICUBIC,
    )


def _background_perturb_image(image: Image.Image) -> Image.Image:
    width, height = image.size
    background = image.resize(
        (max(width, 64), max(height, 64)),
        _RESAMPLING.LANCZOS,
    ).filter(ImageFilter.GaussianBlur(radius=max(min(width, height) / 24.0, 2.0)))
    overlay_scale = 0.86
    overlay = image.resize(
        (
            max(int(width * overlay_scale), 1),
            max(int(height * overlay_scale), 1),
        ),
        _RESAMPLING.LANCZOS,
    )
    canvas = background.copy()
    offset = (
        max((canvas.width - overlay.width) // 2, 0),
        max((canvas.height - overlay.height) // 2, 0),
    )
    canvas.paste(overlay, offset)
    return canvas


def _materialize_auto_support_variant(
    source_path: str,
    variant_name: str,
    output_dir: str,
    image_factory,
) -> str:
    absolute_source_path = os.path.abspath(source_path)
    try:
        stat_result = os.stat(absolute_source_path)
    except OSError:
        return ""

    source_signature = "|".join(
        [
            absolute_source_path,
            variant_name,
            str(int(stat_result.st_mtime_ns)),
            str(int(stat_result.st_size)),
        ]
    )
    digest = hashlib.sha1(source_signature.encode("utf-8")).hexdigest()[:16]
    stem = os.path.splitext(os.path.basename(absolute_source_path))[0]
    output_path = os.path.join(output_dir, f"{stem}-{variant_name}-{digest}.jpg")
    if os.path.exists(output_path):
        return output_path

    image = _open_rgb_image(absolute_source_path)
    if image is None:
        return ""

    try:
        variant_image = image_factory(image)
        os.makedirs(output_dir, exist_ok=True)
        variant_image.save(output_path, format="JPEG", quality=78, optimize=True)
    except Exception:
        return ""
    return output_path


def _resolve_auto_support_variant_path(
    source_path: str,
    variant_name: str,
    output_dir: str,
    image_factory,
    *,
    materialize_missing: bool,
) -> str:
    absolute_source_path = os.path.abspath(source_path)
    try:
        stat_result = os.stat(absolute_source_path)
    except OSError:
        return ""

    source_signature = "|".join(
        [
            absolute_source_path,
            variant_name,
            str(int(stat_result.st_mtime_ns)),
            str(int(stat_result.st_size)),
        ]
    )
    digest = hashlib.sha1(source_signature.encode("utf-8")).hexdigest()[:16]
    stem = os.path.splitext(os.path.basename(absolute_source_path))[0]
    output_path = os.path.join(output_dir, f"{stem}-{variant_name}-{digest}.jpg")
    if os.path.exists(output_path):
        return output_path
    if not materialize_missing:
        return ""
    return _materialize_auto_support_variant(
        source_path,
        variant_name=variant_name,
        output_dir=output_dir,
        image_factory=image_factory,
    )


def build_auto_product_support_records(
    catalog_records: Sequence[LiveCatalogImageRecord],
    *,
    output_dir: str | os.PathLike[str] | None = None,
    max_source_images_per_product: int = 3,
    max_records_per_product: int = 5,
    include_original_images: bool = True,
    enable_center_crop: bool = True,
    enable_compressed: bool = True,
    enable_perspective: bool = True,
    enable_background_perturb: bool = True,
    materialize_missing_variants: bool = True,
) -> List[LiveProductSupportRecord]:
    grouped_records: Dict[str, List[LiveCatalogImageRecord]] = {}
    for record in catalog_records:
        product_id = str(record.product_id or "").strip()
        if not product_id:
            continue
        image_path = str(record.image_path or "").strip()
        if not image_path or not os.path.exists(image_path):
            continue
        grouped_records.setdefault(product_id, []).append(record)

    resolved_output_dir = _resolve_auto_support_output_dir(str(output_dir or ""))
    source_limit = max(int(max_source_images_per_product or 0), 1)
    record_limit = max(int(max_records_per_product or 0), 1)
    variant_builders = [
        ("center", _center_crop_image, bool(enable_center_crop)),
        ("compressed", _compress_image, bool(enable_compressed)),
        ("perspective", _perspective_warp_image, bool(enable_perspective)),
        ("background", _background_perturb_image, bool(enable_background_perturb)),
    ]

    support_records: List[LiveProductSupportRecord] = []
    for product_id, product_records in grouped_records.items():
        ordered_records = sorted(
            product_records,
            key=lambda item: (int(getattr(item, "image_index", 0) or 0), str(item.image_path)),
        )[:source_limit]
        if not ordered_records:
            continue

        title = str(getattr(ordered_records[0], "title", "") or "")
        product_queries = _collect_unique_product_queries(ordered_records)
        added_paths: set[str] = set()
        product_support_records: List[LiveProductSupportRecord] = []

        def _append_support_record(image_path: str) -> bool:
            normalized_path = str(image_path or "").strip()
            if (
                not normalized_path
                or normalized_path in added_paths
                or not os.path.exists(normalized_path)
                or len(product_support_records) >= record_limit
            ):
                return False
            added_paths.add(normalized_path)
            product_support_records.append(
                LiveProductSupportRecord(
                    expected_product_id=product_id,
                    image_path=normalized_path,
                    title=title,
                    product_queries=list(product_queries),
                )
            )
            return True

        if include_original_images:
            for record in ordered_records:
                if len(product_support_records) >= record_limit:
                    break
                _append_support_record(record.image_path)

        if len(product_support_records) < record_limit:
            for record in ordered_records:
                for variant_name, image_factory, enabled in variant_builders:
                    if not enabled or len(product_support_records) >= record_limit:
                        continue
                    variant_path = _resolve_auto_support_variant_path(
                        record.image_path,
                        variant_name=variant_name,
                        output_dir=resolved_output_dir,
                        image_factory=image_factory,
                        materialize_missing=bool(materialize_missing_variants),
                    )
                    _append_support_record(variant_path)
                if len(product_support_records) >= record_limit:
                    break

        support_records.extend(product_support_records)

    return support_records


def _load_auto_product_support_records_from_env(
    catalog_records: Sequence[LiveCatalogImageRecord],
) -> List[LiveProductSupportRecord]:
    if not _env_bool("LIVE_IMAGE_SEARCH_AUTO_PRODUCT_SUPPORT_ENABLED", True):
        return []

    return build_auto_product_support_records(
        catalog_records,
        output_dir=os.getenv("LIVE_IMAGE_SEARCH_AUTO_PRODUCT_SUPPORT_DIR", ""),
        max_source_images_per_product=_env_int(
            "LIVE_IMAGE_SEARCH_AUTO_PRODUCT_SUPPORT_MAX_SOURCE_IMAGES",
            3,
        ),
        max_records_per_product=_env_int(
            "LIVE_IMAGE_SEARCH_AUTO_PRODUCT_SUPPORT_MAX_RECORDS",
            5,
        ),
        include_original_images=_env_bool(
            "LIVE_IMAGE_SEARCH_AUTO_PRODUCT_SUPPORT_INCLUDE_ORIGINALS",
            True,
        ),
        enable_center_crop=_env_bool(
            "LIVE_IMAGE_SEARCH_AUTO_PRODUCT_SUPPORT_CENTER_CROP",
            True,
        ),
        enable_compressed=_env_bool(
            "LIVE_IMAGE_SEARCH_AUTO_PRODUCT_SUPPORT_COMPRESSED",
            True,
        ),
        enable_perspective=_env_bool(
            "LIVE_IMAGE_SEARCH_AUTO_PRODUCT_SUPPORT_PERSPECTIVE",
            True,
        ),
        enable_background_perturb=_env_bool(
            "LIVE_IMAGE_SEARCH_AUTO_PRODUCT_SUPPORT_BACKGROUND",
            True,
        ),
        materialize_missing_variants=_env_bool(
            "LIVE_IMAGE_SEARCH_AUTO_PRODUCT_SUPPORT_MATERIALIZE_MISSING",
            False,
        ),
    )


def load_runtime_product_support_records(
    catalog_records: Sequence[LiveCatalogImageRecord],
) -> List[LiveProductSupportRecord]:
    support_mode = _get_product_support_mode()
    external_records: List[LiveProductSupportRecord] = []
    manifest_records: List[LiveProductSupportRecord] = []
    auto_records: List[LiveProductSupportRecord] = []

    if _env_bool("LIVE_IMAGE_SEARCH_EXTERNAL_PRODUCT_SUPPORT_ENABLED", True):
        external_records = load_external_product_support_records(catalog_records)
    if support_mode in {"manifest", "merge"}:
        manifest_records = load_product_support_records_from_manifest(
            os.getenv("LIVE_IMAGE_SEARCH_PRODUCT_SUPPORT_MANIFEST", "")
        )
    if support_mode in {"auto", "merge"}:
        auto_records = _load_auto_product_support_records_from_env(catalog_records)
    merged_records: List[LiveProductSupportRecord] = []
    seen: set[tuple[str, str]] = set()

    for record in list(manifest_records) + list(external_records) + list(auto_records):
        product_id = str(getattr(record, "expected_product_id", "") or "").strip()
        image_path = str(getattr(record, "image_path", "") or "").strip()
        key = (product_id, image_path)
        if not product_id or not image_path or key in seen:
            continue
        seen.add(key)
        merged_records.append(
            LiveProductSupportRecord(
                expected_product_id=product_id,
                image_path=image_path,
                title=str(getattr(record, "title", "") or ""),
                product_queries=list(
                    getattr(record, "product_queries", None)
                    or getattr(record, "queries", None)
                    or []
                ),
            )
        )
    return merged_records


def _build_queries(row: Dict[str, Any]) -> List[str]:
    values = [
        row.get("title"),
        row.get("english_title"),
        row.get("description"),
        row.get("item_id"),
    ]
    return [str(value).strip() for value in values if str(value or "").strip()]


def _parse_json_list(raw_value: Any) -> Optional[List[Any]]:
    if raw_value in (None, "", []):
        return None
    if isinstance(raw_value, list):
        return raw_value
    try:
        parsed = json.loads(str(raw_value))
        if isinstance(parsed, list):
            return parsed
    except Exception:
        return None
    return None


def _parse_json_float_array(raw_value: Any) -> Any:
    if raw_value is None:
        return None
    if isinstance(raw_value, np.ndarray):
        return raw_value.astype(np.float32, copy=False).flatten()
    if isinstance(raw_value, (bytes, bytearray, memoryview)):
        raw_bytes = bytes(raw_value)
        if not raw_bytes or len(raw_bytes) % np.dtype(np.float32).itemsize != 0:
            return None
        return np.frombuffer(raw_bytes, dtype=np.float32).copy().flatten()
    if isinstance(raw_value, str):
        stripped = raw_value.strip()
        if not stripped:
            return None
        if stripped.startswith("[") and stripped.endswith("]"):
            stripped = stripped[1:-1].strip()
        if stripped and all(char not in stripped for char in "[]{}"):
            vector = np.fromstring(stripped, sep=",", dtype=np.float32)
            if vector.size > 0:
                return vector
        return _parse_json_list(raw_value)
    if isinstance(raw_value, list):
        try:
            return np.asarray(raw_value, dtype=np.float32).flatten()
        except Exception:
            return raw_value
    return raw_value


def _resolve_product_support_manifest_path(raw_path: str) -> str:
    manifest_path = str(raw_path or "").strip()
    if not manifest_path:
        return ""

    if os.path.isabs(manifest_path):
        return manifest_path

    backend_dir = os.path.dirname(__file__)
    project_root = os.path.dirname(backend_dir)
    candidates = [
        manifest_path,
        os.path.join(backend_dir, manifest_path),
        os.path.join(project_root, manifest_path),
    ]
    for candidate in candidates:
        absolute_candidate = os.path.abspath(candidate)
        if os.path.exists(absolute_candidate):
            return absolute_candidate
    return os.path.abspath(candidates[0])


def load_product_support_records_from_manifest(
    manifest_path: str | os.PathLike[str],
) -> List[LiveProductSupportRecord]:
    resolved_path = _resolve_product_support_manifest_path(str(manifest_path or ""))
    if not resolved_path or not os.path.exists(resolved_path):
        return []

    try:
        with open(resolved_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return []

    manifest_dir = os.path.dirname(resolved_path)

    def _resolve_image_path(raw_image_path: Any) -> str:
        image_path = str(raw_image_path or "").strip()
        if not image_path:
            return ""
        if not os.path.isabs(image_path):
            image_path = os.path.abspath(os.path.join(manifest_dir, image_path))
        return image_path if os.path.exists(image_path) else ""

    records: List[LiveProductSupportRecord] = []
    items = payload.get("items") if isinstance(payload, dict) else None
    if isinstance(items, list):
        for item in items:
            product_id = str(item.get("item_id") or item.get("product_id") or "").strip()
            if not product_id:
                continue
            title = str(item.get("title") or "")
            product_queries = list(item.get("queries", []) or [])
            for image in item.get("support_images") or item.get("query_images") or []:
                image_path = _resolve_image_path(
                    image.get("local_path") or image.get("image_path") or image.get("path")
                )
                if not image_path:
                    continue
                records.append(
                    LiveProductSupportRecord(
                        expected_product_id=product_id,
                        image_path=image_path,
                        title=title,
                        product_queries=product_queries,
                    )
                )
        return records

    rows = payload if isinstance(payload, list) else payload.get("records", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return records

    for row in rows:
        product_id = str(row.get("expected_product_id") or row.get("product_id") or "").strip()
        image_path = _resolve_image_path(row.get("image_path") or row.get("local_path") or row.get("path"))
        if not product_id or not image_path:
            continue
        records.append(
            LiveProductSupportRecord(
                expected_product_id=product_id,
                image_path=image_path,
                title=str(row.get("title") or ""),
                product_queries=list(row.get("product_queries") or row.get("queries") or []),
            )
        )

    return records


def build_catalog_records(rows: Sequence[Dict[str, Any]]) -> List[LiveCatalogImageRecord]:
    records: List[LiveCatalogImageRecord] = []
    for row in rows:
        record = build_catalog_record(row)
        if record is not None:
            records.append(record)
    return records


def build_catalog_record(
    row: Dict[str, Any],
    *,
    preserve_cached_arrays: bool = False,
) -> Optional[LiveCatalogImageRecord]:
    image_path = str(row.get("image_path") or "").strip()
    if not image_path:
        return None
    retrieval_embedding = row.get("retrieval_embedding")
    retrieval_color_hist = row.get("retrieval_color_hist")
    return LiveCatalogImageRecord(
        product_id=str(row.get("product_id") or row.get("id") or ""),
        item_id=str(row.get("item_id") or ""),
        title=str(row.get("title") or ""),
        english_title=str(row.get("english_title") or ""),
        description=str(row.get("description") or ""),
        shop_name=str(row.get("shop_name") or ""),
        image_path=image_path,
        image_index=int(row.get("image_index") or 0),
        product_url=str(row.get("product_url") or ""),
        cnfans_url=str(row.get("cnfans_url") or ""),
        acbuy_url=str(row.get("acbuy_url") or ""),
        rule_enabled=bool(row.get("ruleEnabled", True)),
        reply_scope=str(row.get("reply_scope") or "all"),
        image_source=str(row.get("image_source") or "product"),
        custom_reply_text=str(row.get("custom_reply_text") or ""),
        custom_reply_images=str(row.get("custom_reply_images") or ""),
        custom_image_urls=str(row.get("custom_image_urls") or ""),
        uploaded_reply_images=str(row.get("uploaded_reply_images") or ""),
        queries=_build_queries(row),
        image_db_id=int(row.get("image_db_id") or 0),
        cache_strategy_name=str(row.get("retrieval_cache_strategy") or ""),
        cache_version=str(row.get("retrieval_cache_version") or ""),
        cache_embedding=(
            retrieval_embedding
            if preserve_cached_arrays and retrieval_embedding not in (None, "", [])
            else _parse_json_float_array(retrieval_embedding)
        ),
        cache_color_hist=(
            retrieval_color_hist
            if preserve_cached_arrays and retrieval_color_hist not in (None, "", [])
            else _parse_json_float_array(retrieval_color_hist)
        ),
        cache_tokens=_parse_json_list(row.get("retrieval_tokens")) or [],
    )


def _build_product_metadata(record: LiveCatalogImageRecord) -> Dict[str, Any]:
    return {
        "english_title": record.english_title,
        "description": record.description,
        "shop_name": record.shop_name,
        "product_url": record.product_url,
        "cnfans_url": record.cnfans_url,
        "acbuy_url": record.acbuy_url,
        "ruleEnabled": record.rule_enabled,
        "reply_scope": record.reply_scope,
        "image_source": record.image_source,
        "custom_reply_text": record.custom_reply_text,
        "custom_reply_images": record.custom_reply_images,
        "custom_image_urls": record.custom_image_urls,
        "uploaded_reply_images": record.uploaded_reply_images,
        "queries": list(record.queries),
    }


def _update_streaming_product_ranking_state(
    ranking_state_by_product: Dict[str, Dict[str, Any]],
    record: LiveCatalogImageRecord,
    score: float,
) -> None:
    product_id = str(record.product_id)
    state = ranking_state_by_product.setdefault(
        product_id,
        {
            "scores": [],
            "best_score": float("-inf"),
            "best_row": {
                "product_id": product_id,
                "title": record.title,
                "image_path": record.image_path,
                "image_index": record.image_index,
            },
        },
    )

    scores = state["scores"]
    scores.append(float(score))
    scores.sort(reverse=True)
    if len(scores) > 5:
        del scores[5:]

    if float(score) > float(state["best_score"]):
        state["best_score"] = float(score)
        state["best_row"] = {
            "product_id": product_id,
            "title": record.title,
            "image_path": record.image_path,
            "image_index": record.image_index,
        }


def _finalize_streaming_product_rankings(
    ranking_state_by_product: Dict[str, Dict[str, Any]],
    top_k: int,
) -> List[Dict[str, Any]]:
    ranked_with_signal = []
    for state in ranking_state_by_product.values():
        scores = list(state.get("scores") or [])
        if not scores:
            continue

        best_score = float(scores[0])
        second_best_score = float(scores[1]) if len(scores) > 1 else 0.0
        top3_mean_score = mean(scores[:3])
        top5_mean_score = mean(scores[:5])
        rank_score = (
            best_score
            + _PRODUCT_RANK_SECOND_BEST_WEIGHT * second_best_score
            + _PRODUCT_RANK_TOP3_MEAN_WEIGHT * top3_mean_score
            + _PRODUCT_RANK_TOP5_MEAN_WEIGHT * top5_mean_score
        )
        ranked_with_signal.append(
            (
                rank_score,
                {
                    **state["best_row"],
                    "score": best_score,
                },
            )
        )

    ranked = [
        item
        for _rank_score, item in sorted(
            ranked_with_signal,
            key=lambda pair: (
                -float(pair[0]),
                -float(pair[1].get("score", 0.0)),
                str(pair[1].get("product_id") or ""),
                int(pair[1].get("image_index") or 0),
                str(pair[1].get("image_path") or ""),
            ),
        )
    ]
    return ranked[: max(int(top_k or 1), 1)]


def build_catalog_records(rows: Sequence[Dict[str, Any]]) -> List[LiveCatalogImageRecord]:
    records: List[LiveCatalogImageRecord] = []
    for row in rows:
        record = build_catalog_record(row)
        if record is not None:
            records.append(record)
    return records


def build_query_record(image_path: str, query_text: str = "") -> LiveQueryRecord:
    normalized_query_text = " ".join(str(query_text or "").strip().split())
    return LiveQueryRecord(
        image_path=image_path,
        query=normalized_query_text,
        product_queries=([normalized_query_text] if normalized_query_text else []),
    )


def build_catalog_record_for_product_image(
    product_row: Dict[str, Any],
    image_path: str,
    image_index: int,
    image_db_id: int = 0,
) -> LiveCatalogImageRecord:
    return build_catalog_records(
        [
            {
                "product_id": product_row.get("id") or product_row.get("product_id"),
                "item_id": product_row.get("item_id"),
                "title": product_row.get("title"),
                "english_title": product_row.get("english_title"),
                "description": product_row.get("description"),
                "product_url": product_row.get("product_url"),
                "cnfans_url": product_row.get("cnfans_url"),
                "acbuy_url": product_row.get("acbuy_url"),
                "shop_name": product_row.get("shop_name"),
                "ruleEnabled": product_row.get("ruleEnabled", True),
                "reply_scope": product_row.get("reply_scope", "all"),
                "image_source": product_row.get("image_source", "product"),
                "custom_reply_text": product_row.get("custom_reply_text", ""),
                "custom_reply_images": product_row.get("custom_reply_images", ""),
                "custom_image_urls": product_row.get("custom_image_urls", ""),
                "uploaded_reply_images": product_row.get("uploaded_reply_images", ""),
                "image_db_id": image_db_id,
                "image_path": image_path,
                "image_index": image_index,
            }
        ]
    )[0]


def _strip_catalog_record_cache_payload(record: LiveCatalogImageRecord) -> LiveCatalogImageRecord:
    if (
        getattr(record, "cache_embedding", None) is None
        and getattr(record, "cache_color_hist", None) is None
        and not list(getattr(record, "cache_tokens", []) or [])
    ):
        return record

    return LiveCatalogImageRecord(
        product_id=record.product_id,
        item_id=record.item_id,
        title=record.title,
        english_title=record.english_title,
        description=record.description,
        shop_name=record.shop_name,
        image_path=record.image_path,
        image_index=record.image_index,
        product_url=record.product_url,
        cnfans_url=record.cnfans_url,
        acbuy_url=record.acbuy_url,
        rule_enabled=record.rule_enabled,
        reply_scope=record.reply_scope,
        image_source=record.image_source,
        custom_reply_text=record.custom_reply_text,
        custom_reply_images=record.custom_reply_images,
        custom_image_urls=record.custom_image_urls,
        uploaded_reply_images=record.uploaded_reply_images,
        queries=list(record.queries),
        image_db_id=record.image_db_id,
        cache_strategy_name=record.cache_strategy_name,
        cache_version=record.cache_version,
        cache_embedding=None,
        cache_color_hist=None,
        cache_tokens=[],
    )


def prepare_catalog_entries(
    strategy: Any,
    catalog_records: Sequence[LiveCatalogImageRecord],
    support_records: Optional[Sequence[LiveProductSupportRecord]] = None,
) -> List[Dict[str, Any]]:
    alias_to_product_id: Dict[str, str] = {}
    for record in catalog_records:
        product_id = str(record.product_id or "").strip()
        if not product_id:
            continue
        alias_to_product_id.setdefault(product_id, product_id)
        item_id = str(getattr(record, "item_id", "") or "").strip()
        if item_id:
            alias_to_product_id.setdefault(item_id, product_id)

    resolved_support_records: List[LiveProductSupportRecord] = []
    for record in support_records or []:
        raw_product_id = str(
            getattr(record, "expected_product_id", "")
            or getattr(record, "product_id", "")
            or ""
        ).strip()
        resolved_product_id = alias_to_product_id.get(raw_product_id, raw_product_id)
        if not resolved_product_id:
            continue
        resolved_support_records.append(
            LiveProductSupportRecord(
                expected_product_id=resolved_product_id,
                image_path=str(getattr(record, "image_path", "") or "").strip(),
                title=str(getattr(record, "title", "") or ""),
                product_queries=list(
                    getattr(record, "product_queries", None)
                    or getattr(record, "queries", None)
                    or []
                ),
            )
        )

    prepared = []
    for record in catalog_records:
        prepared.append(
            {
                "record": _strip_catalog_record_cache_payload(record),
                "context": strategy.prepare_catalog_image(record),
            }
        )

    set_support_records = getattr(strategy, "set_product_support_records", None)
    if callable(set_support_records):
        try:
            set_support_records(resolved_support_records, prepared_catalog=prepared)
        except TypeError as exc:
            if "prepared_catalog" not in str(exc):
                raise
            set_support_records(resolved_support_records)
    return prepared


def _rank_products_for_query(
    strategy: Any,
    prepared_catalog: Sequence[Dict[str, Any]],
    query_context: Dict[str, Any],
    top_k: int,
    cancel_event: Optional[Any] = None,
) -> Dict[str, Any]:
    if _is_search_cancelled(cancel_event):
        return {"ranked_products": []}

    fast_ranker = getattr(strategy, "rank_products_fast", None)
    if callable(fast_ranker):
        if _is_search_cancelled(cancel_event):
            return {"ranked_products": []}
        fast_result = fast_ranker(
            query_context=query_context,
            prepared_catalog=prepared_catalog,
            top_k=top_k,
        )
        if isinstance(fast_result, dict):
            return fast_result
        if fast_result is not None:
            return {"ranked_products": list(fast_result)}

    custom_ranker = getattr(strategy, "rank_products", None)
    if callable(custom_ranker):
        if _is_search_cancelled(cancel_event):
            return {"ranked_products": []}
        custom_result = custom_ranker(
            query_context=query_context,
            prepared_catalog=prepared_catalog,
            top_k=top_k,
        )
        if isinstance(custom_result, dict):
            return custom_result
        if custom_result is not None:
            return {"ranked_products": list(custom_result)}

    image_rankings: List[Dict[str, Any]] = []
    for entry in prepared_catalog:
        if _is_search_cancelled(cancel_event):
            break
        record: LiveCatalogImageRecord = entry["record"]
        score = float(strategy.score(query_context, entry["context"]))
        image_rankings.append(
            {
                "product_id": record.product_id,
                "title": record.title,
                "score": score,
                "image_path": record.image_path,
                "image_index": record.image_index,
            }
        )

    return {
        "ranked_products": aggregate_product_rankings(image_rankings, top_k=max(int(top_k or 1), 1)),
    }


def rank_query_products(
    strategy: Any,
    prepared_catalog: Sequence[Dict[str, Any]],
    query_record: LiveQueryRecord,
    top_k: int = 5,
    threshold: float = 0.0,
    user_shops: Optional[Sequence[str]] = None,
    cancel_event: Optional[Any] = None,
    query_context: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    if _is_search_cancelled(cancel_event):
        return []

    if query_context is None:
        query_context = strategy.prepare_query_image(query_record)
    product_metadata: Dict[str, Dict[str, Any]] = {}

    if user_shops is None:
        allowed_shops: Optional[set[str]] = None
    else:
        allowed_shops = {str(shop).strip() for shop in user_shops if str(shop).strip()}
        if not allowed_shops:
            return []

    filtered_catalog = []
    for entry in prepared_catalog:
        if _is_search_cancelled(cancel_event):
            return []
        record: LiveCatalogImageRecord = entry["record"]
        if allowed_shops is not None and record.shop_name not in allowed_shops:
            continue
        filtered_catalog.append(entry)
        product_metadata.setdefault(
            record.product_id,
            {
                "english_title": record.english_title,
                "description": record.description,
                "shop_name": record.shop_name,
                "product_url": record.product_url,
                "cnfans_url": record.cnfans_url,
                "acbuy_url": record.acbuy_url,
                "ruleEnabled": record.rule_enabled,
                "reply_scope": record.reply_scope,
                "image_source": record.image_source,
                "custom_reply_text": record.custom_reply_text,
                "custom_reply_images": record.custom_reply_images,
                "custom_image_urls": record.custom_image_urls,
                "uploaded_reply_images": record.uploaded_reply_images,
                "queries": list(record.queries),
            },
        )

    rank_payload = _rank_products_for_query(
        strategy,
        filtered_catalog,
        query_context,
        top_k=max(int(top_k or 1), 1),
        cancel_event=cancel_event,
    )
    ranked_products = list(rank_payload.get("ranked_products", []))
    filtered_ranked_products = [
        {
            **item,
            **product_metadata.get(str(item["product_id"]), {}),
        }
        for item in ranked_products
        if float(item.get("score", 0.0)) >= float(threshold or 0.0)
    ]
    return filtered_ranked_products[: max(int(top_k or 1), 1)]


_strategy_instance_registry: Dict[str, Any] = {}
_strategy_instance_lock = Lock()


def get_retrieval_strategy_instance(strategy_name: str, strategy_factory=None):
    if strategy_factory is not None:
        return strategy_factory(strategy_name)

    try:
        from .benchmarks.strategies import create_strategy
    except ImportError:
        from benchmarks.strategies import create_strategy

    with _strategy_instance_lock:
        strategy = _strategy_instance_registry.get(strategy_name)
        if strategy is None:
            strategy = create_strategy(strategy_name)
            _strategy_instance_registry[strategy_name] = strategy
        return strategy


def backfill_product_image_retrieval_cache(
    db_handle,
    strategy_name: str,
    limit: Optional[int] = None,
    strategy_factory=None,
) -> Dict[str, int]:
    effective_limit = max(int(limit or 0), 0) or None
    rows = list(
        db_handle.get_searchable_product_image_records(
            strategy_name=strategy_name,
            require_cache=False,
            only_missing_cache=True,
            limit=effective_limit,
        )
    )
    catalog_records = build_catalog_records(rows)
    strategy = get_retrieval_strategy_instance(strategy_name, strategy_factory=strategy_factory)

    processed = 0
    skipped = 0
    failed = 0
    max_items = max(int(limit or 0), 0)

    for record in catalog_records:
        has_cache = bool(record.cache_strategy_name == strategy_name)
        if has_cache:
            skipped += 1
            continue

        image_lookup = getattr(db_handle, "get_image_info_by_id", None)
        if callable(image_lookup) and not image_lookup(record.image_db_id):
            skipped += 1
            continue

        if max_items and processed >= max_items:
            break

        try:
            payload = strategy.build_catalog_cache_payload(record)
            if not payload.get("embedding"):
                failed += 1
                continue
            success = db_handle.upsert_product_image_retrieval_cache(
                image_db_id=record.image_db_id,
                strategy_name=strategy_name,
                cache_version=str(payload.get("cache_version") or ""),
                embedding=payload.get("embedding"),
                color_hist=payload.get("color_hist"),
                tokens=payload.get("tokens"),
            )
            if success:
                processed += 1
            else:
                if callable(image_lookup) and not image_lookup(record.image_db_id):
                    skipped += 1
                else:
                    failed += 1
        except Exception:
            failed += 1

    return {
        "processed": processed,
        "skipped": skipped,
        "failed": failed,
        "total": len(catalog_records),
    }


def build_product_image_retrieval_cache_payload(
    strategy_name: str,
    product_row: Dict[str, Any],
    image_path: str,
    image_index: int,
    image_db_id: int = 0,
    strategy_factory=None,
) -> Dict[str, Any]:
    strategy = get_retrieval_strategy_instance(strategy_name, strategy_factory=strategy_factory)
    record = build_catalog_record_for_product_image(
        product_row=product_row,
        image_path=image_path,
        image_index=image_index,
        image_db_id=image_db_id,
    )
    return strategy.build_catalog_cache_payload(record)


def strategy_requires_persisted_catalog_cache(strategy_name: str) -> bool:
    return str(strategy_name or "").strip() == "siglip2_rerank"


class LiveImageRetriever:
    def __init__(self, db_handle, strategy_name: str):
        self.db = db_handle
        self.strategy_name = strategy_name
        self._lock = Lock()
        self._catalog_signature: Optional[Tuple[Any, ...]] = None
        self._prepared_catalog: List[Dict[str, Any]] = []
        self._scoped_catalog_cache: OrderedDict[Tuple[str, ...], Tuple[Any, List[Dict[str, Any]], Tuple[Any, ...], int]] = OrderedDict()
        self._scoped_catalog_prepare_inflight: set[Tuple[str, ...]] = set()
        self._strategy = None
        self._catalog_refresh_required = True
        self._prepare_inflight = False
        self._refresh_generation = 0
        self._query_context_cache: OrderedDict[Tuple[Any, ...], Tuple[float, Dict[str, Any]]] = OrderedDict()
        self._query_context_cache_lock = Lock()

    @staticmethod
    def _clone_query_context_value(value: Any) -> Any:
        if isinstance(value, np.ndarray):
            return value.copy()
        if isinstance(value, dict):
            return {
                key: LiveImageRetriever._clone_query_context_value(inner_value)
                for key, inner_value in value.items()
            }
        if isinstance(value, list):
            return [LiveImageRetriever._clone_query_context_value(item) for item in value]
        if isinstance(value, tuple):
            return tuple(LiveImageRetriever._clone_query_context_value(item) for item in value)
        if isinstance(value, set):
            return set(value)
        return value

    @classmethod
    def _clone_query_context(cls, query_context: Dict[str, Any]) -> Dict[str, Any]:
        return {
            key: cls._clone_query_context_value(value)
            for key, value in (query_context or {}).items()
        }

    @staticmethod
    def _build_query_context_cache_key(
        image_path: str,
        query_text: str,
    ) -> Optional[Tuple[Any, ...]]:
        resolved_path = str(image_path or "").strip()
        if not resolved_path or not os.path.exists(resolved_path):
            return None
        try:
            stat_result = os.stat(resolved_path)
            digest = hashlib.sha1()
            with open(resolved_path, "rb") as image_file:
                while True:
                    chunk = image_file.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
        except OSError:
            return None
        return (
            "LiveImageRetriever",
            int(stat_result.st_size),
            digest.hexdigest(),
            str(query_text or ""),
        )

    def _get_cached_query_context(
        self,
        image_path: str,
        query_text: str,
    ) -> Optional[Dict[str, Any]]:
        ttl_seconds = _env_float("LIVE_IMAGE_SEARCH_QUERY_CONTEXT_CACHE_TTL_SECONDS", 30.0)
        max_entries = max(_env_int("LIVE_IMAGE_SEARCH_QUERY_CONTEXT_CACHE_MAX_ENTRIES", 64), 0)
        if ttl_seconds <= 0 or max_entries <= 0:
            return None

        cache_key = self._build_query_context_cache_key(image_path, query_text)
        if cache_key is None:
            return None

        now = perf_counter()
        with self._query_context_cache_lock:
            expired_keys = [
                key
                for key, (expires_at, _payload) in self._query_context_cache.items()
                if expires_at <= now
            ]
            for key in expired_keys:
                self._query_context_cache.pop(key, None)

            cached = self._query_context_cache.get(cache_key)
            if cached is None:
                return None
            expires_at, payload = cached
            if expires_at <= now:
                self._query_context_cache.pop(cache_key, None)
                return None
            self._query_context_cache.move_to_end(cache_key)
            return self._clone_query_context(payload)

    def _store_cached_query_context(
        self,
        image_path: str,
        query_text: str,
        query_context: Dict[str, Any],
    ) -> None:
        ttl_seconds = _env_float("LIVE_IMAGE_SEARCH_QUERY_CONTEXT_CACHE_TTL_SECONDS", 30.0)
        max_entries = max(_env_int("LIVE_IMAGE_SEARCH_QUERY_CONTEXT_CACHE_MAX_ENTRIES", 64), 0)
        if ttl_seconds <= 0 or max_entries <= 0:
            return

        cache_key = self._build_query_context_cache_key(image_path, query_text)
        if cache_key is None:
            return

        expires_at = perf_counter() + ttl_seconds
        payload = self._clone_query_context(query_context)
        with self._query_context_cache_lock:
            self._query_context_cache[cache_key] = (expires_at, payload)
            self._query_context_cache.move_to_end(cache_key)
            while len(self._query_context_cache) > max_entries:
                self._query_context_cache.popitem(last=False)

    def _load_catalog_rows(self) -> List[Dict[str, Any]]:
        return list(
            self.db.get_searchable_product_image_records(
                strategy_name=self.strategy_name,
                require_cache=strategy_requires_persisted_catalog_cache(self.strategy_name),
            )
        )

    def _load_catalog_rows_for_shops(self, shop_names: Sequence[str]) -> List[Dict[str, Any]]:
        return list(
            self.db.get_searchable_product_image_records(
                strategy_name=self.strategy_name,
                require_cache=strategy_requires_persisted_catalog_cache(self.strategy_name),
                shop_names=shop_names,
                ordered=False,
            )
        )

    def _get_strategy_instance(self):
        if self._strategy is not None:
            return self._strategy

        strategy = get_retrieval_strategy_instance(self.strategy_name)
        self._strategy = strategy
        return strategy

    def _supports_streaming_search(self, strategy) -> bool:
        if not callable(getattr(self.db, 'iter_searchable_product_image_records', None)):
            return False
        return should_enable_streaming_live_search(
            self.strategy_name,
            strategy,
            streaming_enabled=_env_bool("LIVE_IMAGE_SEARCH_STREAMING_ENABLED", False),
            force_streaming=_env_bool("LIVE_IMAGE_SEARCH_STREAMING_FORCE", False),
            require_persisted_cache=strategy_requires_persisted_catalog_cache(self.strategy_name),
        )

    @staticmethod
    def _build_signature(rows: Sequence[Dict[str, Any]]) -> Tuple[int, int, str]:
        if not rows:
            return (0, 0, "")
        digest = hashlib.sha1()
        max_image_db_id = max(int(row.get("image_db_id") or 0) for row in rows)
        for row in sorted(
            rows,
            key=lambda item: (
                int(item.get("image_db_id") or 0),
                str(item.get("image_path") or ""),
            ),
        ):
            digest.update(
                "|".join(
                    [
                        str(row.get("product_id") or row.get("id") or ""),
                        str(row.get("item_id") or ""),
                        str(row.get("shop_name") or ""),
                        str(row.get("image_db_id") or 0),
                        str(row.get("image_index") or 0),
                        str(row.get("image_path") or ""),
                        str(row.get("retrieval_cache_strategy") or ""),
                        str(row.get("retrieval_cache_version") or ""),
                    ]
                ).encode("utf-8")
            )
            digest.update(b"\n")
        return (len(rows), max_image_db_id, digest.hexdigest())

    @staticmethod
    def _build_support_signature(manifest_path: str) -> Tuple[str, int, int]:
        resolved_path = _resolve_product_support_manifest_path(manifest_path)
        if not resolved_path:
            return ("", 0, 0)
        try:
            stat_result = os.stat(resolved_path)
        except OSError:
            return (resolved_path, 0, 0)
        return (
            resolved_path,
            int(stat_result.st_mtime_ns),
            int(stat_result.st_size),
        )

    def invalidate(self):
        with self._lock:
            self._refresh_generation += 1
            self._catalog_refresh_required = True
            self._scoped_catalog_cache.clear()
            self._scoped_catalog_prepare_inflight.clear()
            if self._catalog_signature is None:
                self._prepared_catalog = []

    def _has_active_catalog_locked(self) -> bool:
        return self._strategy is not None and self._catalog_signature is not None

    def _build_prepared_catalog_snapshot(self):
        try:
            from .benchmarks.strategies import create_strategy
        except ImportError:
            from benchmarks.strategies import create_strategy

        rows = self._load_catalog_rows()
        catalog_records = build_catalog_records(rows)
        support_manifest_path = os.getenv("LIVE_IMAGE_SEARCH_PRODUCT_SUPPORT_MANIFEST", "")
        support_signature = self._build_support_signature(support_manifest_path)
        runtime_signature = _build_runtime_env_signature(self.strategy_name)
        signature = self._build_signature(rows) + support_signature + runtime_signature
        support_records = load_runtime_product_support_records(catalog_records)

        strategy = create_strategy(self.strategy_name)
        prepared_catalog = prepare_catalog_entries(
            strategy,
            catalog_records,
            support_records=support_records,
        )
        return strategy, prepared_catalog, signature

    def _apply_prepared_catalog_locked(
        self,
        strategy,
        prepared_catalog: List[Dict[str, Any]],
        signature: Tuple[Any, ...],
        refresh_generation: int,
    ) -> None:
        self._strategy = strategy
        self._catalog_signature = signature
        self._prepared_catalog = prepared_catalog
        self._prepare_inflight = False
        self._catalog_refresh_required = self._refresh_generation != refresh_generation

    def _refresh_catalog_in_background(self, refresh_generation: int) -> None:
        try:
            strategy, prepared_catalog, signature = self._build_prepared_catalog_snapshot()
        except Exception:
            logger.exception(
                "Live retrieval catalog refresh failed: strategy=%s",
                self.strategy_name,
            )
            with self._lock:
                self._prepare_inflight = False
            return

        with self._lock:
            self._apply_prepared_catalog_locked(
                strategy,
                prepared_catalog,
                signature,
                refresh_generation,
            )

    def _start_background_refresh_locked(self) -> bool:
        if self._prepare_inflight:
            return False

        refresh_generation = self._refresh_generation
        self._prepare_inflight = True
        prepare_thread = Thread(
            target=self._refresh_catalog_in_background,
            args=(refresh_generation,),
            daemon=True,
            name=f"live-catalog-refresh-{self.strategy_name}",
        )
        prepare_thread.start()
        return True

    def _prepare_scoped_catalog_in_background(self, shop_scope: Tuple[str, ...]) -> None:
        try:
            self._ensure_scoped_prepared_catalog(shop_scope)
        except Exception:
            logger.exception(
                "Scoped live retrieval catalog prepare failed: strategy=%s shops=%s",
                self.strategy_name,
                list(shop_scope),
            )
        finally:
            with self._lock:
                self._scoped_catalog_prepare_inflight.discard(shop_scope)

    def _start_scoped_catalog_prepare_in_background(
        self,
        user_shops: Optional[Sequence[str]],
    ) -> bool:
        shop_scope = self._normalize_shop_scope(user_shops)
        if not shop_scope:
            return False

        with self._lock:
            cached = self._scoped_catalog_cache.get(shop_scope)
            if cached is not None and cached[3] == self._refresh_generation:
                return False
            if shop_scope in self._scoped_catalog_prepare_inflight:
                return False
            self._scoped_catalog_prepare_inflight.add(shop_scope)

        prepare_thread = Thread(
            target=self._prepare_scoped_catalog_in_background,
            args=(shop_scope,),
            daemon=True,
            name=f"live-scoped-catalog-prepare-{self.strategy_name}",
        )
        prepare_thread.start()
        return True

    def _prepare_catalog_now(self):
        with self._lock:
            if self._has_active_catalog_locked() and not self._catalog_refresh_required:
                return self._strategy, self._prepared_catalog

            refresh_generation = self._refresh_generation
            self._prepare_inflight = True

        try:
            strategy, prepared_catalog, signature = self._build_prepared_catalog_snapshot()
        except Exception:
            with self._lock:
                self._prepare_inflight = False
            raise

        with self._lock:
            self._apply_prepared_catalog_locked(
                strategy,
                prepared_catalog,
                signature,
                refresh_generation,
            )
            return self._strategy, self._prepared_catalog

    @staticmethod
    def _normalize_shop_scope(user_shops: Optional[Sequence[str]]) -> Optional[Tuple[str, ...]]:
        if user_shops is None:
            return None
        normalized = tuple(
            sorted(
                {
                    str(shop).strip()
                    for shop in user_shops
                    if str(shop).strip()
                }
            )
        )
        return normalized

    def _build_prepared_catalog_snapshot_for_shops(self, shop_scope: Tuple[str, ...]):
        try:
            from .benchmarks.strategies import create_strategy
        except ImportError:
            from benchmarks.strategies import create_strategy

        cached_snapshot = self._load_scoped_prepared_catalog_from_disk(shop_scope)
        if cached_snapshot is not None:
            return cached_snapshot

        rows = self._load_catalog_rows_for_shops(shop_scope)
        catalog_records = build_catalog_records(rows)
        runtime_signature = _build_runtime_env_signature(self.strategy_name)
        signature = self._build_scoped_catalog_signature(shop_scope, rows=rows)
        if signature is None:
            signature = self._build_signature(rows) + ("shops",) + shop_scope + runtime_signature

        strategy = self._get_strategy_instance() or create_strategy(self.strategy_name)
        prepared_catalog = prepare_catalog_entries(strategy, catalog_records)
        self._save_scoped_prepared_catalog_to_disk(
            shop_scope,
            strategy,
            prepared_catalog,
            signature,
        )
        return strategy, prepared_catalog, signature

    def _get_scoped_catalog_cache_dir(self) -> str:
        raw_dir = str(os.getenv("LIVE_IMAGE_SEARCH_SCOPED_CATALOG_DISK_CACHE_DIR", "") or "").strip()
        if raw_dir:
            return raw_dir if os.path.isabs(raw_dir) else os.path.abspath(raw_dir)
        return os.path.join(os.path.dirname(__file__), "data", "live_retrieval_scoped_catalogs")

    def _build_scoped_catalog_signature(
        self,
        shop_scope: Tuple[str, ...],
        rows: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> Optional[Tuple[Any, ...]]:
        runtime_signature = _build_runtime_env_signature(self.strategy_name)
        signature_loader = getattr(self.db, "get_searchable_product_image_records_signature", None)
        if callable(signature_loader):
            summary = signature_loader(
                strategy_name=self.strategy_name,
                require_cache=strategy_requires_persisted_catalog_cache(self.strategy_name),
                shop_names=shop_scope,
            )
            return (
                _SCOPED_CATALOG_DISK_CACHE_VERSION,
                self.strategy_name,
                shop_scope,
                int((summary or {}).get("count") or 0),
                int((summary or {}).get("max_image_db_id") or 0),
                int((summary or {}).get("max_product_id") or 0),
                str((summary or {}).get("max_product_updated_at") or ""),
                str((summary or {}).get("max_cache_updated_at") or ""),
                runtime_signature,
            )
        if rows is None:
            return None
        return (
            _SCOPED_CATALOG_DISK_CACHE_VERSION,
            self.strategy_name,
            shop_scope,
            self._build_signature(rows),
            runtime_signature,
        )

    def _get_scoped_catalog_cache_path(self, shop_scope: Tuple[str, ...], signature: Tuple[Any, ...]) -> str:
        digest = hashlib.sha1(
            json.dumps(signature, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        return os.path.join(self._get_scoped_catalog_cache_dir(), f"{digest}.pkl")

    def _load_scoped_prepared_catalog_from_disk(self, shop_scope: Tuple[str, ...]):
        signature = self._build_scoped_catalog_signature(shop_scope)
        if signature is None:
            return None
        cache_path = self._get_scoped_catalog_cache_path(shop_scope, signature)
        if not os.path.exists(cache_path):
            return None

        try:
            with open(cache_path, "rb") as cache_file:
                payload = pickle.load(cache_file)
            if payload.get("signature") != signature:
                return None
            prepared_catalog = list(payload.get("prepared_catalog") or [])
            strategy = self._get_strategy_instance()
            logger.info(
                "Loaded scoped live retrieval catalog cache: strategy=%s shops=%s catalog_size=%s path=%s",
                self.strategy_name,
                list(shop_scope),
                len(prepared_catalog),
                cache_path,
            )
            return strategy, prepared_catalog, signature
        except Exception:
            logger.exception(
                "加载店铺实时检索目录磁盘缓存失败: strategy=%s shops=%s path=%s",
                self.strategy_name,
                list(shop_scope),
                cache_path,
            )
            try:
                os.unlink(cache_path)
            except OSError:
                pass
            return None

    def _save_scoped_prepared_catalog_to_disk(
        self,
        shop_scope: Tuple[str, ...],
        strategy,
        prepared_catalog: List[Dict[str, Any]],
        signature: Tuple[Any, ...],
    ) -> None:
        if _env_bool("LIVE_IMAGE_SEARCH_SCOPED_CATALOG_DISK_CACHE_DISABLED", False):
            return
        cache_dir = self._get_scoped_catalog_cache_dir()
        cache_path = self._get_scoped_catalog_cache_path(shop_scope, signature)
        try:
            os.makedirs(cache_dir, exist_ok=True)
            payload = {
                "version": _SCOPED_CATALOG_DISK_CACHE_VERSION,
                "strategy": self.strategy_name,
                "signature": signature,
                "prepared_catalog": prepared_catalog,
            }
            fd, tmp_path = tempfile.mkstemp(
                prefix=".tmp-",
                suffix=".pkl",
                dir=cache_dir,
            )
            with os.fdopen(fd, "wb") as cache_file:
                pickle.dump(payload, cache_file, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp_path, cache_path)
            logger.info(
                "Saved scoped live retrieval catalog cache: strategy=%s shops=%s catalog_size=%s path=%s",
                self.strategy_name,
                list(shop_scope),
                len(prepared_catalog),
                cache_path,
            )
        except Exception:
            logger.exception(
                "保存店铺实时检索目录磁盘缓存失败: strategy=%s shops=%s",
                self.strategy_name,
                list(shop_scope),
            )
            try:
                if "tmp_path" in locals() and os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except OSError:
                pass

    def _ensure_scoped_prepared_catalog(
        self,
        user_shops: Optional[Sequence[str]],
    ) -> Optional[Tuple[Any, List[Dict[str, Any]]]]:
        shop_scope = self._normalize_shop_scope(user_shops)
        if not shop_scope:
            return None

        refresh_generation = self._refresh_generation
        with self._lock:
            cached = self._scoped_catalog_cache.get(shop_scope)
            if cached is not None and cached[3] == refresh_generation:
                self._scoped_catalog_cache.move_to_end(shop_scope)
                return cached[0], cached[1]

        strategy, prepared_catalog, signature = self._build_prepared_catalog_snapshot_for_shops(shop_scope)
        max_scopes = max(_env_int("LIVE_IMAGE_SEARCH_SCOPED_CATALOG_CACHE_SCOPES", 8), 1)
        with self._lock:
            if refresh_generation != self._refresh_generation:
                return strategy, prepared_catalog
            self._strategy = strategy
            self._scoped_catalog_cache[shop_scope] = (
                strategy,
                prepared_catalog,
                signature,
                refresh_generation,
            )
            self._scoped_catalog_cache.move_to_end(shop_scope)
            while len(self._scoped_catalog_cache) > max_scopes:
                self._scoped_catalog_cache.popitem(last=False)
        return strategy, prepared_catalog

    def _get_cached_scoped_prepared_catalog(
        self,
        user_shops: Optional[Sequence[str]],
    ) -> Optional[Tuple[Any, List[Dict[str, Any]]]]:
        shop_scope = self._normalize_shop_scope(user_shops)
        if not shop_scope:
            return None

        refresh_generation = self._refresh_generation
        with self._lock:
            cached = self._scoped_catalog_cache.get(shop_scope)
            if cached is not None and cached[3] == refresh_generation:
                self._scoped_catalog_cache.move_to_end(shop_scope)
                return cached[0], cached[1]

        cached_snapshot = self._load_scoped_prepared_catalog_from_disk(shop_scope)
        if cached_snapshot is None:
            return None

        strategy, prepared_catalog, signature = cached_snapshot
        max_scopes = max(_env_int("LIVE_IMAGE_SEARCH_SCOPED_CATALOG_CACHE_SCOPES", 8), 1)
        with self._lock:
            if refresh_generation != self._refresh_generation:
                return strategy, prepared_catalog
            self._strategy = strategy
            self._scoped_catalog_cache[shop_scope] = (
                strategy,
                prepared_catalog,
                signature,
                refresh_generation,
            )
            self._scoped_catalog_cache.move_to_end(shop_scope)
            while len(self._scoped_catalog_cache) > max_scopes:
                self._scoped_catalog_cache.popitem(last=False)
        return strategy, prepared_catalog

    def load_scoped_prepared_catalog_if_cached(
        self,
        user_shops: Optional[Sequence[str]],
    ) -> bool:
        shop_scope = self._normalize_shop_scope(user_shops)
        if not shop_scope:
            return False

        refresh_generation = self._refresh_generation
        with self._lock:
            cached = self._scoped_catalog_cache.get(shop_scope)
            if cached is not None and cached[3] == refresh_generation:
                self._scoped_catalog_cache.move_to_end(shop_scope)
                return True

        cached_snapshot = self._load_scoped_prepared_catalog_from_disk(shop_scope)
        if cached_snapshot is None:
            return False

        strategy, prepared_catalog, signature = cached_snapshot
        max_scopes = max(_env_int("LIVE_IMAGE_SEARCH_SCOPED_CATALOG_CACHE_SCOPES", 8), 1)
        with self._lock:
            if refresh_generation != self._refresh_generation:
                return False
            self._strategy = strategy
            fast_context_loader = getattr(strategy, "_get_fast_rank_catalog_contexts", None)
            if callable(fast_context_loader):
                try:
                    fast_context_loader(prepared_catalog)
                except Exception:
                    logger.exception(
                        "预构建店铺实时检索矩阵失败: strategy=%s shops=%s",
                        self.strategy_name,
                        list(shop_scope),
                    )
            self._scoped_catalog_cache[shop_scope] = (
                strategy,
                prepared_catalog,
                signature,
                refresh_generation,
            )
            self._scoped_catalog_cache.move_to_end(shop_scope)
            while len(self._scoped_catalog_cache) > max_scopes:
                self._scoped_catalog_cache.popitem(last=False)
        return True

    def _ensure_prepared_catalog(self):
        with self._lock:
            if self._has_active_catalog_locked():
                if self._catalog_refresh_required:
                    self._start_background_refresh_locked()
                return self._strategy, self._prepared_catalog
            started = self._start_background_refresh_locked()
        if started:
            raise LiveCatalogPreparingError(
                f"Live retrieval catalog is preparing: strategy={self.strategy_name}"
            )
        raise LiveCatalogPreparingError(
            f"Live retrieval catalog is already preparing: strategy={self.strategy_name}"
        )

    def _search_streaming(
        self,
        image_path: str,
        query_text: str = "",
        top_k: int = 5,
        threshold: float = 0.0,
        user_shops: Optional[Sequence[str]] = None,
        cancel_event: Optional[Any] = None,
    ) -> Dict[str, Any]:
        if _is_search_cancelled(cancel_event):
            return {
                "strategy": self.strategy_name,
                "catalog_size": 0,
                "ranked_products": [],
                "top1_score": 0.0,
                "top1_margin": 0.0,
                "streaming": True,
            }

        started_at = perf_counter()
        strategy = self._get_strategy_instance()
        query_record = build_query_record(image_path=image_path, query_text=query_text)
        query_prepare_started_at = perf_counter()
        query_context = self._get_cached_query_context(image_path, query_text)
        query_context_cache_hit = query_context is not None
        if query_context is None:
            query_context = strategy.prepare_query_image(query_record)
            self._store_cached_query_context(image_path, query_text, query_context)
        query_prepare_elapsed = perf_counter() - query_prepare_started_at
        if _is_search_cancelled(cancel_event):
            return {
                "strategy": self.strategy_name,
                "catalog_size": 0,
                "ranked_products": [],
                "top1_score": 0.0,
                "top1_margin": 0.0,
                "streaming": True,
            }

        if user_shops is None:
            allowed_shops: Optional[set[str]] = None
            normalized_user_shops = None
        else:
            normalized_user_shops = [
                str(shop).strip()
                for shop in user_shops
                if str(shop).strip()
            ]
            if not normalized_user_shops:
                return {
                    "strategy": self.strategy_name,
                    "catalog_size": 0,
                    "ranked_products": [],
                    "top1_score": 0.0,
                    "top1_margin": 0.0,
                    "streaming": True,
                }
            allowed_shops = set(normalized_user_shops)

        ranking_state_by_product: Dict[str, Dict[str, Any]] = {}
        product_metadata: Dict[str, Dict[str, Any]] = {}
        catalog_size = 0
        record_build_elapsed = 0.0
        catalog_prepare_elapsed = 0.0
        score_elapsed = 0.0
        next_progress_log_after = float(_STREAMING_PROGRESS_LOG_INTERVAL_SECONDS)

        for row in self.db.iter_searchable_product_image_records(
            strategy_name=self.strategy_name,
            require_cache=True,
            only_missing_cache=False,
            limit=None,
            shop_names=normalized_user_shops,
            ordered=False,
        ):
            if _is_search_cancelled(cancel_event):
                break
            raw_shop_name = str(row.get("shop_name") or "")
            if allowed_shops is not None and raw_shop_name not in allowed_shops:
                continue

            record_build_started_at = perf_counter()
            record = build_catalog_record(row, preserve_cached_arrays=True)
            record_build_elapsed += perf_counter() - record_build_started_at
            if record is None:
                continue

            catalog_size += 1
            product_metadata.setdefault(record.product_id, _build_product_metadata(record))
            catalog_prepare_started_at = perf_counter()
            catalog_context = strategy.prepare_catalog_image(record)
            catalog_prepare_elapsed += perf_counter() - catalog_prepare_started_at
            score_started_at = perf_counter()
            score = float(strategy.score(query_context, catalog_context))
            score_elapsed += perf_counter() - score_started_at
            _update_streaming_product_ranking_state(
                ranking_state_by_product,
                record,
                score,
            )
            total_elapsed = perf_counter() - started_at
            if total_elapsed >= next_progress_log_after:
                logger.warning(
                    "Live retrieval streaming progress: strategy=%s elapsed=%.2fs query_prepare=%.2fs record_build=%.2fs catalog_prepare=%.2fs score=%.2fs catalog_size=%s query_cache_hit=%s shops=%s",
                    self.strategy_name,
                    total_elapsed,
                    query_prepare_elapsed,
                    record_build_elapsed,
                    catalog_prepare_elapsed,
                    score_elapsed,
                    catalog_size,
                    query_context_cache_hit,
                    normalized_user_shops,
                )
                next_progress_log_after += float(_STREAMING_PROGRESS_LOG_INTERVAL_SECONDS)

        ranked_products = _finalize_streaming_product_rankings(
            ranking_state_by_product,
            top_k=max(int(top_k or 1), 1),
        )
        filtered_ranked_products = [
            {
                **item,
                **product_metadata.get(str(item["product_id"]), {}),
            }
            for item in ranked_products
            if float(item.get("score", 0.0)) >= float(threshold or 0.0)
        ][: max(int(top_k or 1), 1)]

        top1_score = float(filtered_ranked_products[0]["score"]) if filtered_ranked_products else 0.0
        top2_score = (
            float(filtered_ranked_products[1]["score"])
            if len(filtered_ranked_products) > 1
            else 0.0
        )
        total_elapsed = perf_counter() - started_at
        if total_elapsed >= 5.0:
            logger.warning(
                "Live retrieval slow search: strategy=%s total=%.2fs query_prepare=%.2fs record_build=%.2fs catalog_prepare=%.2fs score=%.2fs catalog_size=%s result_count=%s query_cache_hit=%s shops=%s",
                self.strategy_name,
                total_elapsed,
                query_prepare_elapsed,
                record_build_elapsed,
                catalog_prepare_elapsed,
                score_elapsed,
                catalog_size,
                len(filtered_ranked_products),
                query_context_cache_hit,
                normalized_user_shops,
            )
        return {
            "strategy": self.strategy_name,
            "catalog_size": catalog_size,
            "ranked_products": filtered_ranked_products,
            "top1_score": top1_score,
            "top1_margin": top1_score - top2_score,
            "streaming": True,
        }

    def search(
        self,
        image_path: str,
        query_text: str = "",
        top_k: int = 5,
        threshold: float = 0.0,
        user_shops: Optional[Sequence[str]] = None,
        cancel_event: Optional[Any] = None,
    ) -> Dict[str, Any]:
        strategy = self._get_strategy_instance()
        with self._lock:
            has_global_catalog = self._has_active_catalog_locked()
            catalog_refresh_required = self._catalog_refresh_required
        if has_global_catalog:
            if catalog_refresh_required and self._supports_streaming_search(strategy):
                return self._search_streaming(
                    image_path=image_path,
                    query_text=query_text,
                    top_k=top_k,
                    threshold=threshold,
                    user_shops=user_shops,
                    cancel_event=cancel_event,
                )
            strategy, prepared_catalog = self._ensure_prepared_catalog()
            scoped_catalog = None
        else:
            shop_scope = self._normalize_shop_scope(user_shops)
            if shop_scope:
                scoped_catalog = self._get_cached_scoped_prepared_catalog(user_shops)
                if scoped_catalog is None:
                    if self._supports_streaming_search(strategy):
                        self._start_scoped_catalog_prepare_in_background(user_shops)
                        return self._search_streaming(
                            image_path=image_path,
                            query_text=query_text,
                            top_k=top_k,
                            threshold=threshold,
                            user_shops=user_shops,
                            cancel_event=cancel_event,
                        )
                    started = self._start_scoped_catalog_prepare_in_background(user_shops)
                    if started:
                        raise LiveCatalogPreparingError(
                            f"Scoped live retrieval catalog is preparing: strategy={self.strategy_name}"
                        )
                    raise LiveCatalogPreparingError(
                        f"Scoped live retrieval catalog is already preparing: strategy={self.strategy_name}"
                    )
            elif self._supports_streaming_search(strategy):
                return self._search_streaming(
                    image_path=image_path,
                    query_text=query_text,
                    top_k=top_k,
                    threshold=threshold,
                    user_shops=user_shops,
                    cancel_event=cancel_event,
                )
            else:
                scoped_catalog = self._ensure_scoped_prepared_catalog(user_shops)
            if scoped_catalog is None:
                if self._supports_streaming_search(strategy):
                    return self._search_streaming(
                        image_path=image_path,
                        query_text=query_text,
                        top_k=top_k,
                        threshold=threshold,
                        user_shops=user_shops,
                        cancel_event=cancel_event,
                    )
                strategy, prepared_catalog = self._ensure_prepared_catalog()
            else:
                strategy, prepared_catalog = scoped_catalog
        query_record = build_query_record(image_path=image_path, query_text=query_text)
        started_at = perf_counter()
        query_prepare_started_at = perf_counter()
        query_context = self._get_cached_query_context(image_path, query_text)
        query_context_cache_hit = query_context is not None
        if query_context is None:
            query_context = strategy.prepare_query_image(query_record)
            self._store_cached_query_context(image_path, query_text, query_context)
        query_prepare_elapsed = perf_counter() - query_prepare_started_at
        rank_started_at = perf_counter()
        ranked_products = rank_query_products(
            strategy=strategy,
            prepared_catalog=prepared_catalog,
            query_record=query_record,
            query_context=query_context,
            top_k=top_k,
            threshold=threshold,
            user_shops=None if scoped_catalog is not None else user_shops,
            cancel_event=cancel_event,
        )
        rank_elapsed = perf_counter() - rank_started_at
        top1_score = float(ranked_products[0]["score"]) if ranked_products else 0.0
        top2_score = float(ranked_products[1]["score"]) if len(ranked_products) > 1 else 0.0
        total_elapsed = perf_counter() - started_at
        if total_elapsed >= 5.0:
            logger.warning(
                "Live retrieval cached search slow: strategy=%s total=%.2fs query_prepare=%.2fs rank=%.2fs catalog_size=%s result_count=%s scoped=%s query_cache_hit=%s shops=%s",
                self.strategy_name,
                total_elapsed,
                query_prepare_elapsed,
                rank_elapsed,
                len(prepared_catalog),
                len(ranked_products),
                scoped_catalog is not None,
                query_context_cache_hit,
                list(user_shops or []),
            )
        return {
            "strategy": self.strategy_name,
            "catalog_size": len(prepared_catalog),
            "ranked_products": ranked_products,
            "top1_score": top1_score,
            "top1_margin": top1_score - top2_score,
        }

    def warm(self) -> Dict[str, Any]:
        strategy = self._get_strategy_instance()
        if should_enable_streaming_live_search(
            self.strategy_name,
            strategy,
            streaming_enabled=_env_bool("LIVE_IMAGE_SEARCH_STREAMING_ENABLED", False),
            force_streaming=_env_bool("LIVE_IMAGE_SEARCH_STREAMING_FORCE", False),
            require_persisted_cache=strategy_requires_persisted_catalog_cache(self.strategy_name),
        ):
            return {
                "strategy": self.strategy_name,
                "catalog_size": 0,
                "streaming": True,
                "skipped_count": True,
            }

        _strategy, prepared_catalog = self._prepare_catalog_now()
        return {
            "strategy": self.strategy_name,
            "catalog_size": len(prepared_catalog),
        }


_retriever_registry: Dict[str, LiveImageRetriever] = {}
_retriever_registry_lock = Lock()


def get_live_image_retriever(db_handle, strategy_name: str):
    with _retriever_registry_lock:
        retriever = _retriever_registry.get(strategy_name)
        if retriever is None:
            retriever = LiveImageRetriever(db_handle=db_handle, strategy_name=strategy_name)
            _retriever_registry[strategy_name] = retriever
        return retriever


def warm_live_image_retriever(db_handle, strategy_name: str) -> Dict[str, Any]:
    return get_live_image_retriever(db_handle, strategy_name).warm()


def warm_live_image_strategy(db_handle, strategy_name: str) -> Dict[str, Any]:
    retriever = get_live_image_retriever(db_handle, strategy_name)
    retriever._get_strategy_instance()
    return {
        "strategy": strategy_name,
        "strategy_ready": True,
    }


def warm_live_image_scoped_catalogs(
    db_handle,
    strategy_name: str,
    shop_scopes: Sequence[Sequence[str]],
) -> Dict[str, Any]:
    retriever = get_live_image_retriever(db_handle, strategy_name)
    loaded = 0
    skipped = 0
    for scope in shop_scopes:
        if retriever.load_scoped_prepared_catalog_if_cached(scope):
            loaded += 1
        else:
            skipped += 1
    return {
        "strategy": strategy_name,
        "loaded": loaded,
        "skipped": skipped,
    }


def invalidate_live_image_retriever(strategy_name: Optional[str] = None):
    with _retriever_registry_lock:
        if strategy_name:
            retriever = _retriever_registry.get(strategy_name)
            if retriever is not None:
                retriever.invalidate()
            return

        for retriever in _retriever_registry.values():
            retriever.invalidate()

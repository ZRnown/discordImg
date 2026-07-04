import json
import logging
import copy
import re
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

try:
    from config import config
except ImportError:
    from .config import config

logger = logging.getLogger(__name__)

GOOGLE_CUSTOM_SEARCH_ENDPOINT = "https://www.googleapis.com/customsearch/v1"
SEARCHAPI_GOOGLE_IMAGES_ENDPOINT = "https://www.searchapi.io/api/v1/search"


def normalize_keyword_image_search_mode(value: Any) -> str:
    candidate = str(value or "manual").strip().lower()
    if candidate in {"manual", "auto"}:
        return candidate
    return "manual"


def normalize_keyword_image_search_max_images(value: Any, default: int = 3) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, 10))


def build_product_send_url(
    product: Optional[Dict[str, Any]],
    website_config: Optional[Dict[str, Any]],
) -> Optional[str]:
    if not isinstance(product, dict) or not isinstance(website_config, dict):
        return None

    weidian_url = str(
        product.get("weidianUrl")
        or product.get("product_url")
        or product.get("productUrl")
        or ""
    ).strip()
    url_template = str(
        website_config.get("url_template")
        or website_config.get("urlTemplate")
        or ""
    ).strip()
    if not weidian_url or not url_template:
        return None

    match = re.search(r"itemID=(\d+)", weidian_url, re.IGNORECASE)
    if not match:
        return None

    return url_template.replace("{id}", match.group(1))


class KeywordImageSearchError(RuntimeError):
    pass


class KeywordImageSearchService:
    def __init__(self):
        self.session = requests.Session()
        self._cache_lock = threading.RLock()
        self._external_cache: OrderedDict[Tuple[Any, ...], Tuple[float, Any]] = OrderedDict()
        self._internal_cache: OrderedDict[Tuple[Any, ...], Tuple[float, Any]] = OrderedDict()
        self._inflight: Dict[Tuple[str, Tuple[Any, ...]], threading.Event] = {}

    @staticmethod
    def _cache_ttl_seconds() -> float:
        try:
            return max(float(getattr(config, "KEYWORD_IMAGE_SEARCH_CACHE_TTL_SECONDS", 300) or 0), 0.0)
        except (TypeError, ValueError):
            return 300.0

    @staticmethod
    def _cache_max_entries() -> int:
        try:
            return max(int(getattr(config, "KEYWORD_IMAGE_SEARCH_CACHE_MAX_ENTRIES", 512) or 0), 0)
        except (TypeError, ValueError):
            return 512

    @staticmethod
    def _normalize_cache_text(value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip()).lower()

    @staticmethod
    def _normalize_cache_shops(user_shops: Optional[List[str]]) -> Tuple[str, ...]:
        return tuple(
            sorted(
                re.sub(r"\s+", " ", str(shop or "").strip()).lower()
                for shop in (user_shops or [])
                if str(shop or "").strip()
            )
        )

    def _get_or_compute_cached(
        self,
        namespace: str,
        cache: OrderedDict,
        key: Tuple[Any, ...],
        compute: Callable[[], Any],
    ) -> Any:
        ttl_seconds = self._cache_ttl_seconds()
        max_entries = self._cache_max_entries()
        if ttl_seconds <= 0 or max_entries <= 0:
            return compute()

        inflight_key = (namespace, key)
        owner = False
        with self._cache_lock:
            now = time.monotonic()
            cached = cache.get(key)
            if cached is not None:
                expires_at, value = cached
                if expires_at > now:
                    cache.move_to_end(key)
                    return copy.deepcopy(value)
                cache.pop(key, None)

            event = self._inflight.get(inflight_key)
            if event is None:
                event = threading.Event()
                self._inflight[inflight_key] = event
                owner = True

        if not owner:
            event.wait()
            with self._cache_lock:
                cached = cache.get(key)
                if cached is not None:
                    expires_at, value = cached
                    if expires_at > time.monotonic():
                        cache.move_to_end(key)
                        return copy.deepcopy(value)
            return compute()

        try:
            value = compute()
            with self._cache_lock:
                cache[key] = (time.monotonic() + ttl_seconds, copy.deepcopy(value))
                cache.move_to_end(key)
                while len(cache) > max_entries:
                    cache.popitem(last=False)
            return value
        finally:
            with self._cache_lock:
                self._inflight.pop(inflight_key, None)
                event.set()

    @staticmethod
    def _resolve_credentials(user_settings: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
        user_settings = user_settings or {}
        provider = str(
            user_settings.get("keyword_image_search_provider")
            or config.KEYWORD_IMAGE_SEARCH_PROVIDER
            or "searchapi_google_maps"
        ).strip().lower()
        api_key = str(
            user_settings.get("keyword_image_search_api_key")
            or (
                config.GOOGLE_IMAGE_SEARCH_API_KEY
                if provider == "google_cse"
                else config.SEARCHAPI_IMAGE_SEARCH_API_KEY
            )
            or ""
        ).strip()
        cx = str(
            user_settings.get("keyword_image_search_cx")
            or config.GOOGLE_IMAGE_SEARCH_CX
            or ""
        ).strip()
        return {"provider": provider, "api_key": api_key, "cx": cx}

    def search_candidates(
        self,
        *,
        query_text: str,
        website_config: Dict[str, Any],
        user_id: Optional[int] = None,
        user_shops: Optional[List[str]] = None,
        max_images: int = 3,
        user_settings: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        normalized_max_images = normalize_keyword_image_search_max_images(max_images)
        credentials = self._resolve_credentials(user_settings)
        provider = str(credentials.get("provider") or "searchapi_google_maps").strip().lower()
        external_cache_key = (
            provider,
            self._normalize_cache_text(query_text),
            normalized_max_images,
            credentials.get("api_key") or "",
            credentials.get("cx") or "",
        )
        if provider == "google_cse":
            external_results = self._get_or_compute_cached(
                "external",
                self._external_cache,
                external_cache_key,
                lambda: self._search_google_images(
                    query_text,
                    normalized_max_images,
                    credentials=credentials,
                ),
            )
        elif provider == "searchapi_google_maps":
            external_results = self._get_or_compute_cached(
                "external",
                self._external_cache,
                external_cache_key,
                lambda: self._search_searchapi_google_maps(
                    query_text,
                    normalized_max_images,
                    credentials=credentials,
                ),
            )
        else:
            provider = "searchapi_google_images"
            external_cache_key = (
                provider,
                self._normalize_cache_text(query_text),
                normalized_max_images,
                credentials.get("api_key") or "",
                credentials.get("cx") or "",
            )
            external_results = self._get_or_compute_cached(
                "external",
                self._external_cache,
                external_cache_key,
                lambda: self._search_searchapi_google_images(
                    query_text,
                    normalized_max_images,
                    credentials=credentials,
                ),
            )

        website_threshold = website_config.get("image_similarity_threshold")
        try:
            threshold = (
                float(website_threshold)
                if website_threshold is not None
                else float(config.DISCORD_SIMILARITY_THRESHOLD)
            )
        except (TypeError, ValueError):
            threshold = float(config.DISCORD_SIMILARITY_THRESHOLD)

        candidates: List[Dict[str, Any]] = []
        matched_result_count = 0

        for result in external_results:
            candidate = {
                "external_image_url": result.get("image_url"),
                "external_page_url": result.get("page_url"),
                "external_title": result.get("title") or "",
                "thumbnail_url": result.get("thumbnail_url"),
                "match_found": False,
                "similarity": None,
                "send_url": None,
                "product": None,
                "search_result": None,
                "error": None,
            }

            try:
                internal_cache_key = (
                    str(result.get("image_url") or "").strip(),
                    self._normalize_cache_text(query_text),
                    int(user_id) if user_id is not None else None,
                    self._normalize_cache_shops(user_shops),
                    round(float(threshold), 4),
                )
                internal_result = self._get_or_compute_cached(
                    "internal",
                    self._internal_cache,
                    internal_cache_key,
                    lambda image_url=result.get("image_url"): self._search_internal_by_image(
                        image_url=image_url,
                        query_text=query_text,
                        user_id=user_id,
                        user_shops=user_shops,
                        threshold=threshold,
                    ),
                )
            except Exception as exc:
                candidate["error"] = str(exc)
                candidates.append(candidate)
                continue

            if internal_result:
                product = internal_result.get("product") or {}
                candidate["match_found"] = True
                candidate["similarity"] = internal_result.get("similarity")
                candidate["product"] = product
                candidate["search_result"] = internal_result
                candidate["send_url"] = build_product_send_url(product, website_config)
                matched_result_count += 1

            candidates.append(candidate)

        return {
            "success": True,
            "provider": provider,
            "external_result_count": len(external_results),
            "matched_result_count": matched_result_count,
            "candidates": candidates,
        }

    def _search_searchapi_google_images(
        self,
        query_text: str,
        max_images: int,
        *,
        credentials: Dict[str, str],
    ) -> List[Dict[str, Any]]:
        api_key = str(credentials.get("api_key") or "").strip()
        if not api_key:
            raise KeywordImageSearchError("未配置 SearchApi 文本搜图 Key")

        response = self.session.get(
            SEARCHAPI_GOOGLE_IMAGES_ENDPOINT,
            params={
                "api_key": api_key,
                "engine": "google_images",
                "q": query_text,
            },
            timeout=float(config.KEYWORD_IMAGE_SEARCH_REQUEST_TIMEOUT_SECONDS),
        )
        if not response.ok:
            try:
                payload = response.json()
            except Exception:
                payload = {}
            message = (
                payload.get("error")
                or payload.get("message")
                or response.text.strip()
                or f"HTTP {response.status_code}"
            )
            raise KeywordImageSearchError(f"SearchApi 文本搜图请求失败: {message}")

        data = response.json()
        items = data.get("images") or []
        results: List[Dict[str, Any]] = []
        for item in items[: normalize_keyword_image_search_max_images(max_images)]:
            original = item.get("original") or {}
            if not isinstance(original, dict):
                original = {"link": str(original or "").strip()}
            thumbnail = item.get("thumbnail") or {}
            if not isinstance(thumbnail, dict):
                thumbnail = {"link": str(thumbnail or "").strip()}
            image_url = str(original.get("link") or item.get("image") or "").strip()
            if not image_url:
                continue

            source = item.get("source") or {}
            if not isinstance(source, dict):
                source = {"link": str(source or "").strip()}
            results.append(
                {
                    "image_url": image_url,
                    "title": str(
                        item.get("title")
                        or source.get("title")
                        or source.get("name")
                        or ""
                    ).strip(),
                    "page_url": str(source.get("link") or "").strip(),
                    "thumbnail_url": str(thumbnail.get("link") or image_url).strip(),
                }
            )
        return results

    def _search_searchapi_google_maps(
        self,
        query_text: str,
        max_images: int,
        *,
        credentials: Dict[str, str],
    ) -> List[Dict[str, Any]]:
        api_key = str(credentials.get("api_key") or "").strip()
        if not api_key:
            raise KeywordImageSearchError("未配置 SearchApi 地图搜图 Key")

        response = self.session.get(
            SEARCHAPI_GOOGLE_IMAGES_ENDPOINT,
            params={
                "api_key": api_key,
                "engine": "google_maps",
                "q": query_text,
            },
            timeout=float(config.KEYWORD_IMAGE_SEARCH_REQUEST_TIMEOUT_SECONDS),
        )
        if not response.ok:
            try:
                payload = response.json()
            except Exception:
                payload = {}
            message = (
                payload.get("error")
                or payload.get("message")
                or response.text.strip()
                or f"HTTP {response.status_code}"
            )
            raise KeywordImageSearchError(f"SearchApi 地图搜图请求失败: {message}")

        data = response.json()
        places = []
        for key in ("local_results", "ads"):
            items = data.get(key) or []
            if isinstance(items, list):
                places.extend(item for item in items if isinstance(item, dict))

        results: List[Dict[str, Any]] = []
        seen_urls = set()
        max_count = normalize_keyword_image_search_max_images(max_images)
        for place in places:
            image_urls: List[str] = []
            raw_images = place.get("images") or []
            if isinstance(raw_images, list):
                image_urls.extend(str(url or "").strip() for url in raw_images)
            thumbnail_url = str(place.get("thumbnail") or "").strip()
            if thumbnail_url:
                image_urls.append(thumbnail_url)

            for image_url in image_urls:
                if not image_url or image_url in seen_urls:
                    continue
                seen_urls.add(image_url)
                results.append(
                    {
                        "image_url": image_url,
                        "title": str(place.get("title") or query_text or "").strip(),
                        "page_url": str(
                            place.get("place_link")
                            or place.get("website")
                            or place.get("reviews_link")
                            or ""
                        ).strip(),
                        "thumbnail_url": thumbnail_url or image_url,
                    }
                )
                if len(results) >= max_count:
                    return results

        return results

    def _search_google_images(
        self,
        query_text: str,
        max_images: int,
        *,
        credentials: Dict[str, str],
    ) -> List[Dict[str, Any]]:
        api_key = str(credentials.get("api_key") or "").strip()
        cx = str(credentials.get("cx") or "").strip()
        if not api_key or not cx:
            raise KeywordImageSearchError("未配置 Google 文本搜图 API Key 或 CX")

        response = self.session.get(
            GOOGLE_CUSTOM_SEARCH_ENDPOINT,
            params={
                "key": api_key,
                "cx": cx,
                "q": query_text,
                "searchType": "image",
                "num": normalize_keyword_image_search_max_images(max_images),
                "safe": "off",
            },
            timeout=float(config.KEYWORD_IMAGE_SEARCH_REQUEST_TIMEOUT_SECONDS),
        )
        if not response.ok:
            try:
                payload = response.json()
            except Exception:
                payload = {}
            message = (
                payload.get("error", {}).get("message")
                or payload.get("message")
                or response.text.strip()
                or f"HTTP {response.status_code}"
            )
            raise KeywordImageSearchError(f"Google 文本搜图请求失败: {message}")

        data = response.json()
        items = data.get("items") or []
        results: List[Dict[str, Any]] = []
        for item in items:
            image_url = str(item.get("link") or "").strip()
            if not image_url:
                continue
            image_meta = item.get("image") or {}
            results.append(
                {
                    "image_url": image_url,
                    "title": str(item.get("title") or "").strip(),
                    "page_url": str(
                        image_meta.get("contextLink") or item.get("displayLink") or ""
                    ).strip(),
                    "thumbnail_url": str(image_meta.get("thumbnailLink") or "").strip(),
                }
            )
        return results

    def _search_internal_by_image(
        self,
        *,
        image_url: Optional[str],
        user_id: Optional[int],
        user_shops: Optional[List[str]],
        threshold: float,
        query_text: str = "",
    ) -> Optional[Dict[str, Any]]:
        if not image_url:
            return None

        payload = {
            "image_url": image_url,
            "threshold": str(threshold),
            "limit": "2",
        }
        query_text = " ".join(str(query_text or "").strip().split())
        if query_text:
            payload["query_text"] = query_text
        if user_id is not None:
            payload["user_id"] = str(user_id)
        if user_shops:
            payload["user_shops"] = json.dumps(user_shops, ensure_ascii=False)

        response = self.session.post(
            f'{config.BACKEND_API_URL.replace("/api", "")}/search_similar',
            data=payload,
            timeout=float(config.KEYWORD_IMAGE_SEARCH_INTERNAL_TIMEOUT_SECONDS),
        )
        if not response.ok:
            if response.status_code in {400, 404}:
                return None
            body = response.text.strip()
            raise KeywordImageSearchError(
                f"内部图搜失败: {response.status_code} {body[:200]}"
            )

        result = response.json()
        results = result.get("results") or []
        if not results:
            return None
        return results[0]


keyword_image_search_service = KeywordImageSearchService()

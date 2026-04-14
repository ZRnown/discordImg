import json
import logging
import re
from typing import Any, Dict, List, Optional

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


def build_product_send_url(product: Optional[Dict[str, Any]], website_config: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(product, dict) or not isinstance(website_config, dict):
        return None

    weidian_url = str(
        product.get("weidianUrl")
        or product.get("product_url")
        or product.get("productUrl")
        or ""
    ).strip()
    url_template = str(website_config.get("url_template") or website_config.get("urlTemplate") or "").strip()
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

    @staticmethod
    def _resolve_credentials(user_settings: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
        user_settings = user_settings or {}
        provider = str(
            user_settings.get("keyword_image_search_provider")
            or config.KEYWORD_IMAGE_SEARCH_PROVIDER
            or "searchapi_google_images"
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
        provider = str(credentials.get("provider") or "searchapi_google_images").strip().lower()
        if provider == "google_cse":
            external_results = self._search_google_images(
                query_text,
                normalized_max_images,
                credentials=credentials,
            )
        else:
            provider = "searchapi_google_images"
            external_results = self._search_searchapi_google_images(
                query_text,
                normalized_max_images,
                credentials=credentials,
            )
        website_threshold = website_config.get("image_similarity_threshold")
        try:
            threshold = float(website_threshold) if website_threshold is not None else float(config.DISCORD_SIMILARITY_THRESHOLD)
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
                internal_result = self._search_internal_by_image(
                    image_url=result.get("image_url"),
                    user_id=user_id,
                    user_shops=user_shops,
                    threshold=threshold,
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
            image_url = str(
                original.get("link")
                or item.get("image")
                or ""
            ).strip()
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
                    "page_url": str(
                        source.get("link")
                        or ""
                    ).strip(),
                    "thumbnail_url": str(
                        thumbnail.get("link")
                        or image_url
                    ).strip(),
                }
            )
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
                    "page_url": str(image_meta.get("contextLink") or item.get("displayLink") or "").strip(),
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
    ) -> Optional[Dict[str, Any]]:
        if not image_url:
            return None

        payload = {
            "image_url": image_url,
            "threshold": str(threshold),
            "limit": "1",
        }
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

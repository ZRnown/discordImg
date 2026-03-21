from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .benchmarks.common import aggregate_product_rankings


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
    queries: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class LiveQueryRecord:
    image_path: str
    query: str = ""
    query_group: str = "live"
    title: str = ""
    expected_product_id: str = ""
    shop_name: str = ""
    product_queries: List[str] = field(default_factory=list)


def _build_queries(row: Dict[str, Any]) -> List[str]:
    values = [
        row.get("title"),
        row.get("english_title"),
        row.get("description"),
        row.get("item_id"),
    ]
    return [str(value).strip() for value in values if str(value or "").strip()]


def build_catalog_records(rows: Sequence[Dict[str, Any]]) -> List[LiveCatalogImageRecord]:
    records: List[LiveCatalogImageRecord] = []
    for row in rows:
        image_path = str(row.get("image_path") or "").strip()
        if not image_path:
            continue
        records.append(
            LiveCatalogImageRecord(
                product_id=str(row.get("product_id") or row.get("id") or ""),
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
            )
        )
    return records


def build_query_record(image_path: str, query_text: str = "") -> LiveQueryRecord:
    normalized_query = str(query_text or "").strip()
    product_queries = [normalized_query] if normalized_query else []
    return LiveQueryRecord(
        image_path=image_path,
        query=normalized_query,
        product_queries=product_queries,
    )


def prepare_catalog_entries(strategy: Any, catalog_records: Sequence[LiveCatalogImageRecord]) -> List[Dict[str, Any]]:
    prepared = []
    for record in catalog_records:
        prepared.append(
            {
                "record": record,
                "context": strategy.prepare_catalog_image(record),
            }
        )
    return prepared


def rank_query_products(
    strategy: Any,
    prepared_catalog: Sequence[Dict[str, Any]],
    query_record: LiveQueryRecord,
    top_k: int = 5,
    threshold: float = 0.0,
    user_shops: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    query_context = strategy.prepare_query_image(query_record)
    image_rankings: List[Dict[str, Any]] = []
    product_metadata: Dict[str, Dict[str, Any]] = {}

    allowed_shops = {str(shop) for shop in (user_shops or []) if str(shop).strip()}

    for entry in prepared_catalog:
        record: LiveCatalogImageRecord = entry["record"]
        if allowed_shops and record.shop_name not in allowed_shops:
            continue

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

    ranked_products = aggregate_product_rankings(image_rankings, top_k=max(int(top_k or 1), 1))
    filtered_ranked_products = [
        {
            **item,
            **product_metadata.get(str(item["product_id"]), {}),
        }
        for item in ranked_products
        if float(item.get("score", 0.0)) >= float(threshold or 0.0)
    ]
    return filtered_ranked_products[: max(int(top_k or 1), 1)]


class LiveImageRetriever:
    def __init__(self, db_handle, strategy_name: str):
        self.db = db_handle
        self.strategy_name = strategy_name
        self._lock = Lock()
        self._catalog_signature: Optional[Tuple[int, int]] = None
        self._prepared_catalog: List[Dict[str, Any]] = []
        self._strategy = None

    def _load_catalog_rows(self) -> List[Dict[str, Any]]:
        return list(self.db.get_searchable_product_image_records())

    @staticmethod
    def _build_signature(rows: Sequence[Dict[str, Any]]) -> Tuple[int, int]:
        if not rows:
            return (0, 0)
        max_image_db_id = max(int(row.get("image_db_id") or 0) for row in rows)
        return (len(rows), max_image_db_id)

    def invalidate(self):
        with self._lock:
            self._catalog_signature = None
            self._prepared_catalog = []
            self._strategy = None

    def _ensure_prepared_catalog(self):
        from .benchmarks.strategies import create_strategy

        rows = self._load_catalog_rows()
        signature = self._build_signature(rows)

        with self._lock:
            if (
                self._strategy is not None
                and self._catalog_signature == signature
                and self._prepared_catalog
            ):
                return self._strategy, self._prepared_catalog

            strategy = create_strategy(self.strategy_name)
            catalog_records = build_catalog_records(rows)
            prepared_catalog = prepare_catalog_entries(strategy, catalog_records)

            self._strategy = strategy
            self._catalog_signature = signature
            self._prepared_catalog = prepared_catalog
            return self._strategy, self._prepared_catalog

    def search(
        self,
        image_path: str,
        query_text: str = "",
        top_k: int = 5,
        threshold: float = 0.0,
        user_shops: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        strategy, prepared_catalog = self._ensure_prepared_catalog()
        query_record = build_query_record(image_path=image_path, query_text=query_text)
        ranked_products = rank_query_products(
            strategy=strategy,
            prepared_catalog=prepared_catalog,
            query_record=query_record,
            top_k=top_k,
            threshold=threshold,
            user_shops=user_shops,
        )
        top1_score = float(ranked_products[0]["score"]) if ranked_products else 0.0
        top2_score = float(ranked_products[1]["score"]) if len(ranked_products) > 1 else 0.0
        return {
            "strategy": self.strategy_name,
            "catalog_size": len(prepared_catalog),
            "ranked_products": ranked_products,
            "top1_score": top1_score,
            "top1_margin": top1_score - top2_score,
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

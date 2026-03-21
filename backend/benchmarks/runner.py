from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence

from .common import aggregate_product_rankings, compute_metrics


@dataclass(frozen=True)
class CatalogImageRecord:
    product_id: str
    title: str
    shop_name: str
    image_path: str
    image_index: int
    source_url: str = ""
    queries: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class QueryImageRecord:
    expected_product_id: str
    title: str
    shop_name: str
    image_path: str
    query: str
    query_group: str
    source_url: str = ""
    product_queries: List[str] = field(default_factory=list)


def build_catalog_records(manifest: Dict[str, Any]) -> List[CatalogImageRecord]:
    records: List[CatalogImageRecord] = []
    for item in manifest.get("items", []):
        for image in item.get("product_images", []):
            records.append(
                CatalogImageRecord(
                    product_id=str(item["item_id"]),
                    title=item.get("title", ""),
                    shop_name=item.get("shop_name", ""),
                    image_path=image["local_path"],
                    image_index=int(image.get("image_index", 0)),
                    source_url=image.get("source_url", ""),
                    queries=list(item.get("queries", [])),
                )
            )
    return records


def build_query_records(manifest: Dict[str, Any]) -> List[QueryImageRecord]:
    records: List[QueryImageRecord] = []
    for item in manifest.get("items", []):
        for image in item.get("query_images", []):
            records.append(
                QueryImageRecord(
                    expected_product_id=str(item["item_id"]),
                    title=item.get("title", ""),
                    shop_name=item.get("shop_name", ""),
                    image_path=image["local_path"],
                    query=image.get("query", ""),
                    query_group=image.get("query_group", "default"),
                    source_url=image.get("source_url", ""),
                    product_queries=list(item.get("queries", [])),
                )
            )
    return records


def _prepare_catalog(strategy: Any, catalog_records: Sequence[CatalogImageRecord]) -> List[Dict[str, Any]]:
    prepared = []
    for record in catalog_records:
        prepared.append(
            {
                "record": record,
                "context": strategy.prepare_catalog_image(record),
            }
        )
    return prepared


def run_benchmark(
    manifest: Dict[str, Any],
    strategy: Any,
    top_k: int = 10,
) -> Dict[str, Any]:
    catalog_records = build_catalog_records(manifest)
    query_records = build_query_records(manifest)
    prepared_catalog = _prepare_catalog(strategy, catalog_records)

    results = []
    for query_record in query_records:
        query_context = strategy.prepare_query_image(query_record)
        image_rankings = []

        for entry in prepared_catalog:
            catalog_record = entry["record"]
            score = float(strategy.score(query_context, entry["context"]))
            image_rankings.append(
                {
                    "product_id": catalog_record.product_id,
                    "title": catalog_record.title,
                    "shop_name": catalog_record.shop_name,
                    "score": score,
                    "image_path": catalog_record.image_path,
                    "image_index": catalog_record.image_index,
                }
            )

        ranked_products = aggregate_product_rankings(image_rankings, top_k=top_k)
        results.append(
            {
                "query_image_path": query_record.image_path,
                "query": query_record.query,
                "query_group": query_record.query_group,
                "title": query_record.title,
                "expected_product_id": query_record.expected_product_id,
                "ranked_products": ranked_products,
            }
        )

    grouped_results = defaultdict(list)
    for result in results:
        grouped_results[result.get("query_group", "default")].append(result)

    return {
        "strategy": getattr(strategy, "name", strategy.__class__.__name__),
        "manifest_meta": dict(manifest.get("meta", {})),
        "dataset": {
            "products": len(manifest.get("items", [])),
            "catalog_images": len(catalog_records),
            "queries": len(query_records),
        },
        "metrics": compute_metrics(results),
        "query_group_metrics": {
            group_name: compute_metrics(group_results)
            for group_name, group_results in grouped_results.items()
        },
        "results": results,
        "failures": list(manifest.get("failures", [])),
    }

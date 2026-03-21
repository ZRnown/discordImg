from __future__ import annotations

from collections import defaultdict
from statistics import mean
import html
import re
from typing import Dict, Iterable, List, Sequence


_BING_MURL_PATTERNS = (
    r'murl&quot;:&quot;(.*?)&quot;',
    r'"murl":"(.*?)"',
)


def parse_bing_image_urls(page_html: str, limit: int = 10) -> List[str]:
    seen = set()
    results: List[str] = []
    for pattern in _BING_MURL_PATTERNS:
        for raw in re.findall(pattern, page_html or ""):
            url = html.unescape(raw).strip()
            if not url or not url.startswith(("http://", "https://")):
                continue
            if url in seen:
                continue
            seen.add(url)
            results.append(url)
            if len(results) >= limit:
                return results
    return results


def aggregate_product_rankings(
    image_rankings: Sequence[Dict],
    top_k: int = 10,
) -> List[Dict]:
    best_by_product: Dict[str, Dict] = {}
    for row in image_rankings:
        product_id = str(row["product_id"])
        score = float(row["score"])
        prev = best_by_product.get(product_id)
        if prev is None or score > prev["score"]:
            best_by_product[product_id] = {
                "product_id": product_id,
                "score": score,
                "title": row.get("title", ""),
                "image_path": row.get("image_path", ""),
                "image_index": row.get("image_index"),
            }
    ranked = sorted(best_by_product.values(), key=lambda item: item["score"], reverse=True)
    return ranked[:top_k]


def compute_metrics(results: Sequence[Dict]) -> Dict[str, float]:
    if not results:
        return {
            "queries": 0,
            "hit_at_1_count": 0,
            "hit_at_1": 0.0,
            "hit_at_3_count": 0,
            "hit_at_3": 0.0,
            "mrr_at_5": 0.0,
        }

    hit_at_1 = 0
    hit_at_3 = 0
    reciprocal_ranks: List[float] = []

    for result in results:
        expected = str(result["expected_product_id"])
        ranked = [str(item["product_id"]) for item in result.get("ranked_products", [])]

        if ranked[:1] == [expected]:
            hit_at_1 += 1
        if expected in ranked[:3]:
            hit_at_3 += 1

        rr = 0.0
        for index, product_id in enumerate(ranked[:5], start=1):
            if product_id == expected:
                rr = 1.0 / index
                break
        reciprocal_ranks.append(rr)

    total = len(results)
    return {
        "queries": total,
        "hit_at_1_count": hit_at_1,
        "hit_at_1": hit_at_1 / total,
        "hit_at_3_count": hit_at_3,
        "hit_at_3": hit_at_3 / total,
        "mrr_at_5": mean(reciprocal_ranks),
    }

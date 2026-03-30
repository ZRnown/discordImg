from __future__ import annotations

from collections import defaultdict
from statistics import mean
import html
import os
import re
from typing import Any, Dict, Iterable, List, Sequence

import numpy as np


_BING_MURL_PATTERNS = (
    r'murl&quot;:&quot;(.*?)&quot;',
    r'"murl":"(.*?)"',
)


def _load_positive_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value if value >= 0 else default


_PRODUCT_RANK_SECOND_BEST_WEIGHT = _load_positive_float(
    "RETRIEVAL_PRODUCT_RANK_SECOND_BEST_WEIGHT",
    0.08,
)
_PRODUCT_RANK_TOP3_MEAN_WEIGHT = _load_positive_float(
    "RETRIEVAL_PRODUCT_RANK_TOP3_MEAN_WEIGHT",
    0.04,
)
_PRODUCT_RANK_TOP5_MEAN_WEIGHT = _load_positive_float(
    "RETRIEVAL_PRODUCT_RANK_TOP5_MEAN_WEIGHT",
    0.0,
)


def _normalize_product_pair(
    left_product_id: str,
    right_product_id: str,
) -> tuple[str, str] | None:
    left = str(left_product_id or "").strip()
    right = str(right_product_id or "").strip()
    if not left or not right or left == right:
        return None
    if left <= right:
        return (left, right)
    return (right, left)


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
    grouped_by_product: Dict[str, List[Dict]] = defaultdict(list)
    for row in image_rankings:
        product_id = str(row["product_id"])
        grouped_by_product[product_id].append(row)

    ranked_with_signal = []
    for product_id, rows in grouped_by_product.items():
        scored_rows = sorted(rows, key=lambda item: float(item.get("score", 0.0)), reverse=True)
        best_row = scored_rows[0]
        best_score = float(best_row.get("score", 0.0))
        second_best_score = (
            float(scored_rows[1].get("score", 0.0)) if len(scored_rows) > 1 else 0.0
        )
        top3_mean_score = mean(float(item.get("score", 0.0)) for item in scored_rows[:3])
        top5_mean_score = mean(float(item.get("score", 0.0)) for item in scored_rows[:5])

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
                    "product_id": product_id,
                    # 阈值判定保持“最高图分数”语义，避免改动现有业务阈值经验。
                    "score": best_score,
                    "title": best_row.get("title", ""),
                    "image_path": best_row.get("image_path", ""),
                    "image_index": best_row.get("image_index"),
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
    return ranked[:top_k]


def merge_scored_product_support_rows(
    base_image_rankings: Sequence[Dict[str, Any]],
    support_rows_by_product: Dict[str, Sequence[Dict[str, Any]]] | None,
    exclude_image_path: str = "",
    support_limit: int = 1,
) -> List[Dict[str, Any]]:
    merged_rows = [dict(item) for item in base_image_rankings]
    max_support_limit = max(int(support_limit or 0), 0)
    if max_support_limit <= 0 or not support_rows_by_product:
        return merged_rows

    excluded_path = str(exclude_image_path or "").strip()
    for rows in support_rows_by_product.values():
        if not rows:
            continue
        active_rows: List[Dict[str, Any]] = []
        for row in rows:
            image_path = str(row.get("image_path") or "").strip()
            if excluded_path and image_path and image_path == excluded_path:
                continue
            active_rows.append(dict(row))

        if not active_rows:
            continue

        active_rows.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
        merged_rows.extend(active_rows[:max_support_limit])

    return merged_rows


def extract_hard_negative_pairs(
    results: Sequence[Dict[str, Any]],
    min_count: int = 2,
    limit: int = 20,
) -> List[tuple[str, str]]:
    pair_counts: Dict[tuple[str, str], int] = defaultdict(int)
    for row in results:
        ranked_products = list(row.get("ranked_products") or [])
        if not ranked_products:
            continue
        expected_product_id = str(row.get("expected_product_id") or "").strip()
        predicted_product_id = str(ranked_products[0].get("product_id") or "").strip()
        pair_key = _normalize_product_pair(expected_product_id, predicted_product_id)
        if pair_key is None:
            continue
        pair_counts[pair_key] += 1

    required_count = max(int(min_count or 0), 1)
    max_pairs = max(int(limit or 0), 0)
    ranked_pairs = [
        pair_key
        for pair_key, count in sorted(
            pair_counts.items(),
            key=lambda item: (-item[1], item[0][0], item[0][1]),
        )
        if count >= required_count
    ]
    if max_pairs <= 0:
        return ranked_pairs
    return ranked_pairs[:max_pairs]


def extract_directional_hard_negative_pairs(
    results: Sequence[Dict[str, Any]],
    min_count: int = 2,
    limit: int = 20,
    near_miss_k: int = 3,
) -> List[tuple[str, str]]:
    pair_counts: Dict[tuple[str, str], int] = defaultdict(int)
    max_near_miss_k = max(int(near_miss_k or 0), 1)
    for row in results:
        ranked_products = list(row.get("ranked_products") or [])
        if not ranked_products:
            continue

        expected_product_id = str(row.get("expected_product_id") or "").strip()
        if not expected_product_id:
            continue

        ranked_product_ids = [
            str(item.get("product_id") or "").strip()
            for item in ranked_products[:max_near_miss_k]
            if str(item.get("product_id") or "").strip()
        ]
        if not ranked_product_ids:
            continue

        if expected_product_id in ranked_product_ids:
            expected_rank_index = ranked_product_ids.index(expected_product_id)
            for mistaken_product_id in ranked_product_ids[:expected_rank_index]:
                if mistaken_product_id != expected_product_id:
                    pair_counts[(expected_product_id, mistaken_product_id)] += 1
            continue

        top1_product_id = ranked_product_ids[0]
        if top1_product_id != expected_product_id:
            pair_counts[(expected_product_id, top1_product_id)] += 1

    required_count = max(int(min_count or 0), 1)
    max_pairs = max(int(limit or 0), 0)
    ranked_pairs = [
        pair_key
        for pair_key, count in sorted(
            pair_counts.items(),
            key=lambda item: (-item[1], item[0][0], item[0][1]),
        )
        if count >= required_count
    ]
    if max_pairs <= 0:
        return ranked_pairs
    return ranked_pairs[:max_pairs]


def extract_query_supervised_pair_samples(
    results: Sequence[Dict[str, Any]],
    min_count: int = 2,
    limit: int = 20,
    near_miss_k: int = 3,
) -> Dict[tuple[str, str], List[Dict[str, str]]]:
    grouped_samples: Dict[tuple[str, str], List[Dict[str, str]]] = defaultdict(list)
    max_near_miss_k = max(int(near_miss_k or 0), 1)

    for row in results:
        query_image_path = str(row.get("query_image_path") or "").strip()
        expected_product_id = str(row.get("expected_product_id") or "").strip()
        ranked_products = list(row.get("ranked_products") or [])
        if not query_image_path or not expected_product_id or not ranked_products:
            continue

        ranked_product_ids = [
            str(item.get("product_id") or "").strip()
            for item in ranked_products[:max_near_miss_k]
            if str(item.get("product_id") or "").strip()
        ]
        if not ranked_product_ids:
            continue

        mistaken_product_ids: List[str] = []
        if expected_product_id in ranked_product_ids:
            expected_rank_index = ranked_product_ids.index(expected_product_id)
            if expected_rank_index == 0:
                mistaken_product_ids = ranked_product_ids[1:max_near_miss_k]
            else:
                mistaken_product_ids = ranked_product_ids[:expected_rank_index]
        else:
            mistaken_product_ids = ranked_product_ids[:1]

        for mistaken_product_id in mistaken_product_ids:
            pair_key = _normalize_product_pair(expected_product_id, mistaken_product_id)
            if pair_key is None:
                continue
            grouped_samples[pair_key].append(
                {
                    "label": expected_product_id,
                    "query_image_path": query_image_path,
                }
            )

    required_count = max(int(min_count or 0), 1)
    max_pairs = max(int(limit or 0), 0)
    ranked_pairs = [
        pair_key
        for pair_key, samples in sorted(
            grouped_samples.items(),
            key=lambda item: (-len(item[1]), item[0][0], item[0][1]),
        )
        if len(samples) >= required_count
    ]
    if max_pairs > 0:
        ranked_pairs = ranked_pairs[:max_pairs]

    return {
        pair_key: list(grouped_samples[pair_key])
        for pair_key in ranked_pairs
    }


def _build_connected_product_clusters(
    directional_pairs: Sequence[tuple[str, str]],
) -> List[tuple[str, ...]]:
    adjacency: Dict[str, set[str]] = defaultdict(set)
    for left_product_id, right_product_id in directional_pairs:
        left = str(left_product_id or "").strip()
        right = str(right_product_id or "").strip()
        if not left or not right or left == right:
            continue
        adjacency[left].add(right)
        adjacency[right].add(left)

    visited: set[str] = set()
    clusters: List[tuple[str, ...]] = []
    for product_id in sorted(adjacency):
        if product_id in visited:
            continue
        stack = [product_id]
        component: List[str] = []
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            component.append(current)
            stack.extend(
                neighbor
                for neighbor in sorted(adjacency.get(current) or set(), reverse=True)
                if neighbor not in visited
            )
        if len(component) >= 2:
            clusters.append(tuple(sorted(component)))
    return clusters


def extract_query_supervised_cluster_samples(
    results: Sequence[Dict[str, Any]],
    min_count: int = 2,
    limit: int = 20,
    near_miss_k: int = 3,
) -> Dict[tuple[str, ...], List[Dict[str, str]]]:
    directional_pairs = extract_directional_hard_negative_pairs(
        results,
        min_count=min_count,
        limit=0,
        near_miss_k=near_miss_k,
    )
    if not directional_pairs:
        return {}

    clusters = _build_connected_product_clusters(directional_pairs)
    if not clusters:
        return {}

    cluster_by_product: Dict[str, tuple[str, ...]] = {}
    for cluster_key in clusters:
        for product_id in cluster_key:
            cluster_by_product[product_id] = cluster_key

    grouped_samples: Dict[tuple[str, ...], List[Dict[str, str]]] = defaultdict(list)
    max_near_miss_k = max(int(near_miss_k or 0), 1)
    for row in results:
        query_image_path = str(row.get("query_image_path") or "").strip()
        expected_product_id = str(row.get("expected_product_id") or "").strip()
        ranked_products = list(row.get("ranked_products") or [])
        if not query_image_path or not expected_product_id or not ranked_products:
            continue

        cluster_key = cluster_by_product.get(expected_product_id)
        if cluster_key is None:
            continue

        ranked_product_ids = [
            str(item.get("product_id") or "").strip()
            for item in ranked_products[:max_near_miss_k]
            if str(item.get("product_id") or "").strip()
        ]
        if not ranked_product_ids:
            continue

        if not any(
            product_id != expected_product_id and product_id in cluster_key
            for product_id in ranked_product_ids
        ):
            continue

        grouped_samples[cluster_key].append(
            {
                "label": expected_product_id,
                "query_image_path": query_image_path,
            }
        )

    required_count = max(int(min_count or 0), 1)
    max_clusters = max(int(limit or 0), 0)
    ranked_clusters = [
        cluster_key
        for cluster_key, samples in sorted(
            grouped_samples.items(),
            key=lambda item: (-len(item[1]), item[0]),
        )
        if len(samples) >= required_count
    ]
    if max_clusters > 0:
        ranked_clusters = ranked_clusters[:max_clusters]

    return {
        cluster_key: list(grouped_samples[cluster_key])
        for cluster_key in ranked_clusters
    }


def select_query_variant_rankings(
    rankings_by_variant: Dict[str, Sequence[Dict]],
    default_variant: str,
    challenger_variant: str,
    challenger_min_delta: float = 0.0,
) -> tuple[str, List[Dict]]:
    default_rankings = list(rankings_by_variant.get(default_variant) or [])
    challenger_rankings = list(rankings_by_variant.get(challenger_variant) or [])

    if not default_rankings:
        return challenger_variant, challenger_rankings
    if not challenger_rankings:
        return default_variant, default_rankings

    threshold = max(float(challenger_min_delta or 0.0), 0.0)
    default_top_score = float(default_rankings[0].get("score", 0.0))
    challenger_top_score = float(challenger_rankings[0].get("score", 0.0))

    if challenger_top_score >= default_top_score + threshold:
        return challenger_variant, challenger_rankings
    return default_variant, default_rankings


def _normalize_classifier_vector(values: Sequence[float]) -> np.ndarray:
    vector = np.asarray(list(values), dtype=np.float32).flatten()
    if vector.size == 0:
        raise ValueError("classifier vector is empty")
    norm = float(np.linalg.norm(vector))
    if norm > 0:
        vector = vector / norm
    return vector


def fit_ridge_classifier(
    features: Sequence[Sequence[float]],
    labels: Sequence[str],
    alpha: float = 1.0,
) -> Dict[str, Any]:
    if not features:
        raise ValueError("features are empty")
    if len(features) != len(labels):
        raise ValueError("features/labels length mismatch")

    normalized_features = np.stack(
        [_normalize_classifier_vector(feature) for feature in features],
        axis=0,
    )
    unique_labels = sorted({str(label) for label in labels})
    if not unique_labels:
        raise ValueError("labels are empty")

    label_to_index = {label: index for index, label in enumerate(unique_labels)}
    y_index = np.asarray([label_to_index[str(label)] for label in labels], dtype=np.int64)
    targets = np.zeros((len(labels), len(unique_labels)), dtype=np.float32)
    targets[np.arange(len(labels)), y_index] = 1.0

    regularization = max(float(alpha or 0.0), 1e-6)
    kernel = normalized_features @ normalized_features.T
    dual = np.linalg.solve(
        kernel + (regularization * np.eye(len(labels), dtype=np.float32)),
        targets,
    )
    weights = normalized_features.T @ dual
    return {
        "labels": unique_labels,
        "label_to_index": label_to_index,
        "weights": weights.astype(np.float32),
    }


def score_ridge_classifier(
    classifier: Dict[str, Any],
    feature: Sequence[float],
) -> Dict[str, float]:
    labels = list(classifier.get("labels") or [])
    weights = np.asarray(classifier.get("weights"), dtype=np.float32)
    if not labels or weights.size == 0:
        return {}

    normalized_feature = _normalize_classifier_vector(feature)
    logits = normalized_feature @ weights
    return {
        str(label): float(logits[index])
        for index, label in enumerate(labels)
    }


def rerank_candidate_products_with_classifier(
    ranked_products: Sequence[Dict[str, Any]],
    classifier_scores: Dict[str, float],
    blend: float,
    candidate_k: int,
) -> List[Dict[str, Any]]:
    reranked_products = [dict(item) for item in ranked_products]
    if not reranked_products:
        return reranked_products

    max_candidates = max(int(candidate_k or 0), 0)
    classifier_blend = max(float(blend or 0.0), 0.0)
    if max_candidates <= 0 or classifier_blend <= 0:
        return reranked_products

    candidate_prefix = reranked_products[:max_candidates]
    if not candidate_prefix:
        return reranked_products

    score_values = [
        float(classifier_scores[str(item.get("product_id", ""))])
        for item in candidate_prefix
        if str(item.get("product_id", "")) in classifier_scores
    ]
    if not score_values:
        return reranked_products

    min_score = min(score_values)
    max_score = max(score_values)

    rescored_prefix = []
    for index, item in enumerate(candidate_prefix):
        product_id = str(item.get("product_id", ""))
        classifier_score = float(classifier_scores.get(product_id, min_score))
        normalized_classifier_score = 0.0
        if max_score - min_score > 1e-9:
            normalized_classifier_score = (classifier_score - min_score) / (max_score - min_score)

        rescored_item = dict(item)
        rescored_item["score"] = float(item.get("score", 0.0)) + (
            classifier_blend * normalized_classifier_score
        )
        rescored_prefix.append((index, rescored_item))

    rescored_prefix.sort(
        key=lambda pair: (float(pair[1].get("score", 0.0)), -pair[0]),
        reverse=True,
    )
    return [item for _index, item in rescored_prefix] + reranked_products[max_candidates:]


def rerank_candidate_products_with_pairwise_classifiers(
    ranked_products: Sequence[Dict[str, Any]],
    pairwise_classifiers: Dict[tuple[str, str], Dict[str, Any]],
    query_feature: Sequence[float] | None,
    blend: float,
    candidate_k: int,
    max_score_gap: float = 0.0,
) -> List[Dict[str, Any]]:
    reranked_products = [dict(item) for item in ranked_products]
    if not reranked_products or query_feature is None:
        return reranked_products

    classifier_blend = max(float(blend or 0.0), 0.0)
    max_candidates = max(int(candidate_k or 0), 0)
    score_gap_gate = max(float(max_score_gap or 0.0), 0.0)
    if classifier_blend <= 0 or max_candidates <= 1 or not pairwise_classifiers:
        return reranked_products

    candidate_prefix = reranked_products[:max_candidates]
    candidate_positions = {
        str(item.get("product_id", "")): index
        for index, item in enumerate(candidate_prefix)
        if str(item.get("product_id", "")).strip()
    }
    if len(candidate_positions) < 2:
        return reranked_products

    pairwise_bonus: Dict[str, float] = defaultdict(float)
    for raw_pair_key, classifier in pairwise_classifiers.items():
        if len(raw_pair_key) != 2:
            continue
        pair_key = _normalize_product_pair(raw_pair_key[0], raw_pair_key[1])
        if pair_key is None:
            continue
        left_product_id, right_product_id = pair_key
        if (
            left_product_id not in candidate_positions
            or right_product_id not in candidate_positions
        ):
            continue

        left_item = candidate_prefix[candidate_positions[left_product_id]]
        right_item = candidate_prefix[candidate_positions[right_product_id]]
        if score_gap_gate > 0:
            current_gap = abs(
                float(left_item.get("score", 0.0)) - float(right_item.get("score", 0.0))
            )
            if current_gap > score_gap_gate:
                continue

        pair_scores = score_ridge_classifier(classifier, query_feature)
        if left_product_id not in pair_scores or right_product_id not in pair_scores:
            continue

        left_pair_score = float(pair_scores[left_product_id])
        right_pair_score = float(pair_scores[right_product_id])
        min_pair_score = min(left_pair_score, right_pair_score)
        max_pair_score = max(left_pair_score, right_pair_score)
        if max_pair_score - min_pair_score <= 1e-9:
            normalized_pair_scores = {
                left_product_id: 0.5,
                right_product_id: 0.5,
            }
        else:
            normalized_pair_scores = {
                left_product_id: (left_pair_score - min_pair_score) / (max_pair_score - min_pair_score),
                right_product_id: (right_pair_score - min_pair_score) / (max_pair_score - min_pair_score),
            }

        for product_id, normalized_pair_score in normalized_pair_scores.items():
            pairwise_bonus[product_id] += classifier_blend * float(normalized_pair_score)

    if not pairwise_bonus:
        return reranked_products

    rescored_prefix = []
    for index, item in enumerate(candidate_prefix):
        rescored_item = dict(item)
        product_id = str(item.get("product_id", ""))
        rescored_item["score"] = float(item.get("score", 0.0)) + float(
            pairwise_bonus.get(product_id, 0.0)
        )
        rescored_prefix.append((index, rescored_item))

    rescored_prefix.sort(
        key=lambda pair: (float(pair[1].get("score", 0.0)), -pair[0]),
        reverse=True,
    )
    return [item for _index, item in rescored_prefix] + reranked_products[max_candidates:]


def rerank_candidate_products_with_pairwise_score_swaps(
    ranked_products: Sequence[Dict[str, Any]],
    pairwise_scores: Dict[tuple[str, str], Dict[str, float]],
    candidate_k: int,
    max_score_gap: float = 0.0,
    pair_margin: float = 0.0,
) -> List[Dict[str, Any]]:
    reranked_products = [dict(item) for item in ranked_products]
    max_candidates = max(int(candidate_k or 0), 0)
    if max_candidates <= 1 or len(reranked_products) < 2 or not pairwise_scores:
        return reranked_products

    prefix_limit = min(max_candidates, len(reranked_products))
    candidate_prefix = reranked_products[:prefix_limit]
    score_gap_gate = max(float(max_score_gap or 0.0), 0.0)
    decision_margin = max(float(pair_margin or 0.0), 0.0)

    for _pass_index in range(max(prefix_limit - 1, 1)):
        swapped = False
        for index in range(prefix_limit - 1):
            upper_item = candidate_prefix[index]
            lower_item = candidate_prefix[index + 1]
            upper_product_id = str(upper_item.get("product_id", "")).strip()
            lower_product_id = str(lower_item.get("product_id", "")).strip()
            pair_key = _normalize_product_pair(upper_product_id, lower_product_id)
            if pair_key is None or pair_key not in pairwise_scores:
                continue

            if score_gap_gate > 0:
                current_gap = abs(
                    float(upper_item.get("score", 0.0)) - float(lower_item.get("score", 0.0))
                )
                if current_gap > score_gap_gate:
                    continue

            score_map = pairwise_scores.get(pair_key) or {}
            upper_score = float(score_map.get(upper_product_id, 0.0))
            lower_score = float(score_map.get(lower_product_id, 0.0))
            if lower_score >= upper_score + decision_margin:
                candidate_prefix[index], candidate_prefix[index + 1] = (
                    candidate_prefix[index + 1],
                    candidate_prefix[index],
                )
                swapped = True

        if not swapped:
            break

    return candidate_prefix + reranked_products[prefix_limit:]


def rerank_candidate_products_with_directional_pairwise_score_swaps(
    ranked_products: Sequence[Dict[str, Any]],
    directional_rules: Sequence[tuple[str, str]],
    pairwise_scores: Dict[tuple[str, str], Dict[str, float]],
    candidate_k: int,
    max_score_gap: float = 0.0,
    pair_margin: float = 0.0,
) -> List[Dict[str, Any]]:
    reranked_products = [dict(item) for item in ranked_products]
    max_candidates = max(int(candidate_k or 0), 0)
    if (
        max_candidates <= 1
        or len(reranked_products) < 2
        or not pairwise_scores
        or not directional_rules
    ):
        return reranked_products

    allowed_swaps = {
        (str(preferred_product_id or "").strip(), str(mistaken_product_id or "").strip())
        for preferred_product_id, mistaken_product_id in directional_rules
        if str(preferred_product_id or "").strip()
        and str(mistaken_product_id or "").strip()
        and str(preferred_product_id or "").strip() != str(mistaken_product_id or "").strip()
    }
    if not allowed_swaps:
        return reranked_products

    prefix_limit = min(max_candidates, len(reranked_products))
    candidate_prefix = reranked_products[:prefix_limit]
    score_gap_gate = max(float(max_score_gap or 0.0), 0.0)
    decision_margin = max(float(pair_margin or 0.0), 0.0)

    for _pass_index in range(max(prefix_limit - 1, 1)):
        swapped = False
        for index in range(prefix_limit - 1):
            upper_item = candidate_prefix[index]
            lower_item = candidate_prefix[index + 1]
            upper_product_id = str(upper_item.get("product_id", "")).strip()
            lower_product_id = str(lower_item.get("product_id", "")).strip()
            if (lower_product_id, upper_product_id) not in allowed_swaps:
                continue

            pair_key = _normalize_product_pair(upper_product_id, lower_product_id)
            if pair_key is None or pair_key not in pairwise_scores:
                continue

            if score_gap_gate > 0:
                current_gap = abs(
                    float(upper_item.get("score", 0.0)) - float(lower_item.get("score", 0.0))
                )
                if current_gap > score_gap_gate:
                    continue

            score_map = pairwise_scores.get(pair_key) or {}
            upper_score = float(score_map.get(upper_product_id, 0.0))
            lower_score = float(score_map.get(lower_product_id, 0.0))
            if lower_score >= upper_score + decision_margin:
                candidate_prefix[index], candidate_prefix[index + 1] = (
                    candidate_prefix[index + 1],
                    candidate_prefix[index],
                )
                swapped = True

        if not swapped:
            break

    return candidate_prefix + reranked_products[prefix_limit:]


def rerank_candidate_products_with_cluster_classifier_scores(
    ranked_products: Sequence[Dict[str, Any]],
    cluster_product_ids: Sequence[str],
    classifier_scores: Dict[str, float],
    blend: float,
    candidate_k: int,
    max_score_gap: float = 0.0,
) -> List[Dict[str, Any]]:
    reranked_products = [dict(item) for item in ranked_products]
    if not reranked_products:
        return reranked_products

    classifier_blend = max(float(blend or 0.0), 0.0)
    max_candidates = max(int(candidate_k or 0), 0)
    score_gap_gate = max(float(max_score_gap or 0.0), 0.0)
    if classifier_blend <= 0 or max_candidates <= 1 or not classifier_scores:
        return reranked_products

    prefix_limit = min(max_candidates, len(reranked_products))
    candidate_prefix = reranked_products[:prefix_limit]
    cluster_members = {
        str(product_id or "").strip()
        for product_id in cluster_product_ids
        if str(product_id or "").strip()
    }
    active_product_ids = [
        str(item.get("product_id") or "").strip()
        for item in candidate_prefix
        if str(item.get("product_id") or "").strip() in cluster_members
        and str(item.get("product_id") or "").strip() in classifier_scores
    ]
    if len(active_product_ids) < 2:
        return reranked_products

    if score_gap_gate > 0:
        active_scores = [
            float(item.get("score", 0.0))
            for item in candidate_prefix
            if str(item.get("product_id") or "").strip() in set(active_product_ids)
        ]
        if active_scores and (max(active_scores) - min(active_scores)) > score_gap_gate:
            return reranked_products

    score_values = [float(classifier_scores[product_id]) for product_id in active_product_ids]
    min_score = min(score_values)
    max_score = max(score_values)

    rescored_prefix = []
    active_product_id_set = set(active_product_ids)
    for index, item in enumerate(candidate_prefix):
        rescored_item = dict(item)
        product_id = str(item.get("product_id") or "").strip()
        if product_id in active_product_id_set:
            classifier_score = float(classifier_scores.get(product_id, min_score))
            normalized_classifier_score = 0.0
            if max_score - min_score > 1e-9:
                normalized_classifier_score = (classifier_score - min_score) / (max_score - min_score)
            rescored_item["score"] = float(item.get("score", 0.0)) + (
                classifier_blend * normalized_classifier_score
            )
        rescored_prefix.append((index, rescored_item))

    rescored_prefix.sort(
        key=lambda pair: (float(pair[1].get("score", 0.0)), -pair[0]),
        reverse=True,
    )
    return [item for _index, item in rescored_prefix] + reranked_products[prefix_limit:]


def rerank_candidate_products_with_directional_classifier_score_swaps(
    ranked_products: Sequence[Dict[str, Any]],
    directional_rules: Sequence[tuple[str, str]],
    classifier_scores: Dict[str, float],
    candidate_k: int,
    max_score_gap: float = 0.0,
    classifier_margin: float = 0.0,
) -> List[Dict[str, Any]]:
    reranked_products = [dict(item) for item in ranked_products]
    max_candidates = max(int(candidate_k or 0), 0)
    if (
        max_candidates <= 1
        or len(reranked_products) < 2
        or not directional_rules
        or not classifier_scores
    ):
        return reranked_products

    allowed_swaps = {
        (str(preferred_product_id or "").strip(), str(mistaken_product_id or "").strip())
        for preferred_product_id, mistaken_product_id in directional_rules
        if str(preferred_product_id or "").strip()
        and str(mistaken_product_id or "").strip()
        and str(preferred_product_id or "").strip() != str(mistaken_product_id or "").strip()
    }
    if not allowed_swaps:
        return reranked_products

    prefix_limit = min(max_candidates, len(reranked_products))
    candidate_prefix = reranked_products[:prefix_limit]
    score_gap_gate = max(float(max_score_gap or 0.0), 0.0)
    decision_margin = max(float(classifier_margin or 0.0), 0.0)
    default_classifier_score = min(float(score) for score in classifier_scores.values())

    for _pass_index in range(max(prefix_limit - 1, 1)):
        swapped = False
        for index in range(prefix_limit - 1):
            upper_item = candidate_prefix[index]
            lower_item = candidate_prefix[index + 1]
            upper_product_id = str(upper_item.get("product_id", "")).strip()
            lower_product_id = str(lower_item.get("product_id", "")).strip()
            if (lower_product_id, upper_product_id) not in allowed_swaps:
                continue
            if lower_product_id not in classifier_scores:
                continue

            if score_gap_gate > 0:
                current_gap = abs(
                    float(upper_item.get("score", 0.0)) - float(lower_item.get("score", 0.0))
                )
                if current_gap > score_gap_gate:
                    continue

            upper_classifier_score = float(classifier_scores.get(upper_product_id, default_classifier_score))
            lower_classifier_score = float(classifier_scores[lower_product_id])
            if lower_classifier_score >= upper_classifier_score + decision_margin:
                candidate_prefix[index], candidate_prefix[index + 1] = (
                    candidate_prefix[index + 1],
                    candidate_prefix[index],
                )
                swapped = True

        if not swapped:
            break

    return candidate_prefix + reranked_products[prefix_limit:]


def rerank_candidate_products_with_directional_pairwise_classifiers(
    ranked_products: Sequence[Dict[str, Any]],
    directional_rules: Sequence[tuple[str, str]],
    pairwise_classifiers: Dict[tuple[str, str], Dict[str, Any]],
    query_feature: Sequence[float] | None,
    blend: float,
    candidate_k: int,
    max_score_gap: float = 0.0,
) -> List[Dict[str, Any]]:
    reranked_products = [dict(item) for item in ranked_products]
    if not reranked_products or query_feature is None:
        return reranked_products

    directional_blend = max(float(blend or 0.0), 0.0)
    max_candidates = max(int(candidate_k or 0), 0)
    score_gap_gate = max(float(max_score_gap or 0.0), 0.0)
    if directional_blend <= 0 or max_candidates <= 1 or not directional_rules:
        return reranked_products

    candidate_prefix = reranked_products[:max_candidates]
    candidate_positions = {
        str(item.get("product_id", "")): index
        for index, item in enumerate(candidate_prefix)
        if str(item.get("product_id", "")).strip()
    }
    if len(candidate_positions) < 2:
        return reranked_products

    directional_bonus: Dict[str, float] = defaultdict(float)
    for preferred_product_id, mistaken_product_id in directional_rules:
        preferred_product_id = str(preferred_product_id or "").strip()
        mistaken_product_id = str(mistaken_product_id or "").strip()
        if (
            not preferred_product_id
            or not mistaken_product_id
            or preferred_product_id == mistaken_product_id
        ):
            continue
        if (
            preferred_product_id not in candidate_positions
            or mistaken_product_id not in candidate_positions
        ):
            continue
        if candidate_positions[mistaken_product_id] >= candidate_positions[preferred_product_id]:
            continue

        preferred_item = candidate_prefix[candidate_positions[preferred_product_id]]
        mistaken_item = candidate_prefix[candidate_positions[mistaken_product_id]]
        if score_gap_gate > 0:
            current_gap = abs(
                float(preferred_item.get("score", 0.0)) - float(mistaken_item.get("score", 0.0))
            )
            if current_gap > score_gap_gate:
                continue

        pair_key = _normalize_product_pair(preferred_product_id, mistaken_product_id)
        if pair_key is None or pair_key not in pairwise_classifiers:
            continue

        pair_scores = score_ridge_classifier(pairwise_classifiers[pair_key], query_feature)
        if preferred_product_id not in pair_scores or mistaken_product_id not in pair_scores:
            continue

        preferred_score = float(pair_scores[preferred_product_id])
        mistaken_score = float(pair_scores[mistaken_product_id])
        if preferred_score <= mistaken_score:
            continue

        directional_bonus[preferred_product_id] += directional_blend

    if not directional_bonus:
        return reranked_products

    rescored_prefix = []
    for index, item in enumerate(candidate_prefix):
        rescored_item = dict(item)
        product_id = str(item.get("product_id", ""))
        rescored_item["score"] = float(item.get("score", 0.0)) + float(
            directional_bonus.get(product_id, 0.0)
        )
        rescored_prefix.append((index, rescored_item))

    rescored_prefix.sort(
        key=lambda pair: (float(pair[1].get("score", 0.0)), -pair[0]),
        reverse=True,
    )
    return [item for _index, item in rescored_prefix] + reranked_products[max_candidates:]


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


def compute_score_threshold_metrics(
    results: Sequence[Dict],
    thresholds: Sequence[float],
) -> List[Dict[str, float]]:
    total = len(results)
    rows: List[Dict[str, float]] = []
    normalized_thresholds = sorted(
        {
            float(value)
            for value in thresholds
            if value is not None
        }
    )
    for threshold in normalized_thresholds:
        accepted = []
        accepted_correct = 0
        for result in results:
            ranked = result.get("ranked_products", [])
            top = ranked[0] if ranked else None
            if not top:
                continue
            if float(top.get("score", 0.0)) < threshold:
                continue
            accepted.append(result)
            if str(top.get("product_id", "")) == str(result.get("expected_product_id", "")):
                accepted_correct += 1

        accepted_queries = len(accepted)
        rows.append(
            {
                "threshold": threshold,
                "accepted_queries": accepted_queries,
                "coverage": (accepted_queries / total) if total else 0.0,
                "accepted_hit_at_1_count": accepted_correct,
                "accepted_hit_at_1": (accepted_correct / accepted_queries) if accepted_queries else 0.0,
                # 这个值表示“总样本里最终直接命中的比例”，便于和原始 Hit@1 对比。
                "effective_hit_at_1": (accepted_correct / total) if total else 0.0,
            }
        )
    return rows

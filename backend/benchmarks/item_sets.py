from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .items import BENCHMARK_ITEMS

DEFAULT_QUERY_GROUP = "clean_web"
DEFAULT_ITEM_SET_NAME = "benchmark-items-v1"


def _clean_queries(values: Iterable[str]) -> List[str]:
    seen = set()
    cleaned: List[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return cleaned


def normalize_item(item: Dict) -> Dict:
    normalized = dict(item)
    normalized["item_id"] = str(item["item_id"])
    normalized["title"] = str(item.get("title", "")).strip()

    raw_query_groups = item.get("query_groups") or {}
    query_groups: Dict[str, List[str]] = {}

    if raw_query_groups:
        for group_name, values in raw_query_groups.items():
            cleaned = _clean_queries(values or [])
            if cleaned:
                query_groups[str(group_name)] = cleaned

    if not query_groups:
        cleaned_queries = _clean_queries(item.get("queries", []) or [])
        if cleaned_queries:
            query_groups[DEFAULT_QUERY_GROUP] = cleaned_queries

    merged_queries: List[str] = []
    seen_queries = set()
    for group_queries in query_groups.values():
        for query in group_queries:
            if query in seen_queries:
                continue
            seen_queries.add(query)
            merged_queries.append(query)

    normalized["query_groups"] = query_groups
    normalized["queries"] = merged_queries
    return normalized


def load_item_set(items_file: Optional[Path | str] = None) -> Tuple[str, List[Dict]]:
    if items_file is None:
        return DEFAULT_ITEM_SET_NAME, [normalize_item(item) for item in BENCHMARK_ITEMS]

    path = Path(items_file)
    raw = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(raw, dict):
        dataset_name = str(raw.get("dataset_name") or path.stem)
        items = raw.get("items", [])
    elif isinstance(raw, list):
        dataset_name = path.stem
        items = raw
    else:
        raise ValueError(f"unsupported item set format: {path}")

    return dataset_name, [normalize_item(item) for item in items]


def flatten_item_queries(item: Dict, selected_groups: Optional[Iterable[str]] = None) -> List[Dict[str, str]]:
    normalized = normalize_item(item)
    query_groups = normalized.get("query_groups", {})

    if selected_groups is None:
        group_names = list(query_groups.keys())
    else:
        wanted = [str(group).strip() for group in selected_groups if str(group).strip()]
        group_names = [group for group in wanted if group in query_groups]

    flattened: List[Dict[str, str]] = []
    for group_name in group_names:
        for query in query_groups.get(group_name, []):
            flattened.append({"text": query, "group": group_name})
    return flattened

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


def _fmt_percent(value: float) -> str:
    return f"{value * 100:.2f}%"


def _render_failures(failures: List[Dict[str, Any]]) -> List[str]:
    if not failures:
        return ["## Dataset Failures", "", "None."]

    lines = ["## Dataset Failures", ""]
    for failure in failures:
        lines.append(f"- `{failure.get('item_id', '')}`: {failure.get('error', '')}")
    return lines


def _render_top1_misses(results: List[Dict[str, Any]]) -> List[str]:
    misses = []
    for result in results:
        ranked = result.get("ranked_products", [])
        top_product_id = ranked[0]["product_id"] if ranked else ""
        if top_product_id != result.get("expected_product_id"):
            misses.append(result)

    if not misses:
        return ["## Top-1 Misses", "", "None."]

    lines = ["## Top-1 Misses", ""]
    for result in misses:
        ranked = result.get("ranked_products", [])
        top = ranked[0] if ranked else {}
        query_group = result.get("query_group", "")
        prefix = f"[{query_group}] " if query_group else ""
        lines.append(
            "- "
            f"{prefix}{result.get('title', '')} / `{result.get('query', '')}` -> "
            f"expected `{result.get('expected_product_id', '')}`, "
            f"predicted `{top.get('product_id', '')}` ({top.get('title', '')}, {top.get('score', 0.0):.4f})"
        )
    return lines


def _render_query_group_metrics(query_group_metrics: Dict[str, Dict[str, Any]]) -> List[str]:
    if not query_group_metrics:
        return []

    lines = [
        "## Query Groups",
        "",
        "| Group | Queries | Hit@1 | Hit@3 | MRR@5 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for group_name, metrics in query_group_metrics.items():
        lines.append(
            f"| {group_name} | {metrics.get('queries', 0)} | "
            f"{_fmt_percent(metrics.get('hit_at_1', 0.0))} | "
            f"{_fmt_percent(metrics.get('hit_at_3', 0.0))} | "
            f"{metrics.get('mrr_at_5', 0.0):.4f} |"
        )
    return lines


def render_markdown_report(report: Dict[str, Any]) -> str:
    dataset = report.get("dataset", {})
    metrics = report.get("metrics", {})
    manifest_meta = report.get("manifest_meta", {})
    dataset_name = manifest_meta.get("dataset_name", "")
    top1_count = metrics.get("hit_at_1_count", 0)
    query_count = metrics.get("queries", 0)
    lines = [
        "# Retrieval Benchmark Report",
        "",
        f"Strategy: `{report.get('strategy', '')}`",
        f"Dataset: `{dataset_name}`" if dataset_name else "Dataset: `unknown`",
        "",
        "## Dataset",
        "",
        f"- Products: {dataset.get('products', 0)}",
        f"- Catalog images: {dataset.get('catalog_images', 0)}",
        f"- Query images: {dataset.get('queries', 0)}",
        "",
        "## Exact Top-1",
        "",
        f"Top-1 exact matches: {top1_count} / {query_count} ({_fmt_percent(metrics.get('hit_at_1', 0.0))})",
        "",
        "## Metrics",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Queries | {metrics.get('queries', 0)} |",
        f"| Hit@1 | {_fmt_percent(metrics.get('hit_at_1', 0.0))} |",
        f"| Hit@3 | {_fmt_percent(metrics.get('hit_at_3', 0.0))} |",
        f"| MRR@5 | {metrics.get('mrr_at_5', 0.0):.4f} |",
        "",
    ]

    query_group_lines = _render_query_group_metrics(report.get("query_group_metrics", {}))
    if query_group_lines:
        lines.extend(query_group_lines)
        lines.append("")

    lines.extend(_render_top1_misses(report.get("results", [])))
    lines.append("")
    lines.extend(_render_failures(report.get("failures", [])))
    return "\n".join(lines) + "\n"


def save_report(report: Dict[str, Any], output_dir: Path) -> Dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{report['strategy']}.json"
    md_path = output_dir / f"{report['strategy']}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown_report(report), encoding="utf-8")
    return {
        "json": str(json_path),
        "markdown": str(md_path),
    }

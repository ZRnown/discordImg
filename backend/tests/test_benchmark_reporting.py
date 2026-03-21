from backend.benchmarks.reporting import render_markdown_report


def test_render_markdown_report_includes_metrics_and_failures():
    report = {
        "strategy": "dummy",
        "manifest_meta": {
            "dataset_name": "tip-v2",
            "query_groups": ["clean_web", "discord_noise"],
        },
        "dataset": {"products": 2, "catalog_images": 3, "queries": 2},
        "metrics": {
            "queries": 2,
            "hit_at_1_count": 1,
            "hit_at_1": 0.5,
            "hit_at_3_count": 2,
            "hit_at_3": 1.0,
            "mrr_at_5": 0.75,
        },
        "query_group_metrics": {
            "clean_web": {
                "queries": 1,
                "hit_at_1_count": 1,
                "hit_at_1": 1.0,
                "hit_at_3_count": 1,
                "hit_at_3": 1.0,
                "mrr_at_5": 1.0,
            },
            "discord_noise": {
                "queries": 1,
                "hit_at_1_count": 0,
                "hit_at_1": 0.0,
                "hit_at_3_count": 1,
                "hit_at_3": 1.0,
                "mrr_at_5": 0.5,
            },
        },
        "results": [
            {
                "title": "Alpha",
                "query": "alpha sneaker",
                "query_group": "clean_web",
                "expected_product_id": "1001",
                "ranked_products": [
                    {"product_id": "1001", "score": 0.95, "title": "Alpha"},
                    {"product_id": "1002", "score": 0.42, "title": "Beta"},
                ],
            },
            {
                "title": "Beta",
                "query": "beta sneaker",
                "query_group": "discord_noise",
                "expected_product_id": "1002",
                "ranked_products": [
                    {"product_id": "1001", "score": 0.77, "title": "Alpha"},
                    {"product_id": "1002", "score": 0.74, "title": "Beta"},
                ],
            },
        ],
        "failures": [{"item_id": "1003", "error": "timeout"}],
    }

    text = render_markdown_report(report)

    assert "# Retrieval Benchmark Report" in text
    assert "Strategy: `dummy`" in text
    assert "Dataset: `tip-v2`" in text
    assert "Top-1 exact matches: 1 / 2 (50.00%)" in text
    assert "| Hit@1 | 50.00% |" in text
    assert "| clean_web | 1 | 100.00% |" in text
    assert "| discord_noise | 1 | 0.00% |" in text
    assert "| MRR@5 | 0.7500 |" in text
    assert "Beta" in text
    assert "discord_noise" in text
    assert "timeout" in text

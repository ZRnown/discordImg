from backend.benchmarks.common import (
    aggregate_product_rankings,
    compute_metrics,
    parse_bing_image_urls,
)


def test_parse_bing_image_urls_deduplicates_and_limits():
    html = """
    <a>murl&quot;:&quot;https://img1.example/a.jpg&quot;</a>
    <a>murl&quot;:&quot;https://img1.example/a.jpg&quot;</a>
    <a>murl&quot;:&quot;https://img2.example/b.jpg&quot;</a>
    <a>"murl":"https://img3.example/c.jpg"</a>
    """

    assert parse_bing_image_urls(html, limit=2) == [
        "https://img1.example/a.jpg",
        "https://img2.example/b.jpg",
    ]


def test_aggregate_product_rankings_keeps_best_image_per_product():
    rankings = [
        {"product_id": "1", "score": 0.2, "title": "A", "image_index": 0},
        {"product_id": "1", "score": 0.8, "title": "A", "image_index": 2},
        {"product_id": "2", "score": 0.5, "title": "B", "image_index": 1},
    ]

    assert aggregate_product_rankings(rankings) == [
        {"product_id": "1", "score": 0.8, "title": "A", "image_path": "", "image_index": 2},
        {"product_id": "2", "score": 0.5, "title": "B", "image_path": "", "image_index": 1},
    ]


def test_compute_metrics_uses_product_rank_positions():
    metrics = compute_metrics(
        [
            {
                "expected_product_id": "1",
                "ranked_products": [{"product_id": "1"}, {"product_id": "2"}],
            },
            {
                "expected_product_id": "3",
                "ranked_products": [{"product_id": "4"}, {"product_id": "3"}],
            },
            {
                "expected_product_id": "5",
                "ranked_products": [{"product_id": "6"}, {"product_id": "7"}],
            },
        ]
    )

    assert metrics == {
        "queries": 3,
        "hit_at_1_count": 1,
        "hit_at_1": 1 / 3,
        "hit_at_3_count": 2,
        "hit_at_3": 2 / 3,
        "mrr_at_5": (1.0 + 0.5 + 0.0) / 3,
    }

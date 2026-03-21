from backend.benchmarks.runner import run_benchmark


class DummyStrategy:
    name = "dummy"

    def prepare_catalog_image(self, record):
        return {
            "product_id": record.product_id,
            "image_path": record.image_path,
        }

    def prepare_query_image(self, record):
        return {
            "expected_product_id": record.expected_product_id,
            "query_path": record.image_path,
        }

    def score(self, query_context, catalog_context):
        expected = query_context["expected_product_id"]
        path = catalog_context["image_path"]

        if expected == "1001":
            if path.endswith("a-1.jpg"):
                return 0.95
            if path.endswith("a-2.jpg"):
                return 0.62
            return 0.40

        if path.endswith("b-1.jpg"):
            return 0.91
        if path.endswith("a-1.jpg"):
            return 0.55
        return 0.30


def test_run_benchmark_ranks_products_from_manifest_queries():
    manifest = {
        "meta": {
            "dataset_name": "tip-v2",
            "query_groups": ["clean_web", "discord_noise"],
        },
        "items": [
            {
                "item_id": "1001",
                "title": "Alpha",
                "shop_name": "shop-a",
                "queries": ["alpha sneaker"],
                "product_images": [
                    {"local_path": "/tmp/a-1.jpg", "image_index": 0},
                    {"local_path": "/tmp/a-2.jpg", "image_index": 1},
                ],
                "query_images": [
                    {
                        "local_path": "/tmp/query-alpha.jpg",
                        "query": "alpha sneaker",
                        "query_group": "clean_web",
                    },
                ],
            },
            {
                "item_id": "1002",
                "title": "Beta",
                "shop_name": "shop-b",
                "queries": ["beta sneaker"],
                "product_images": [
                    {"local_path": "/tmp/b-1.jpg", "image_index": 0},
                ],
                "query_images": [
                    {
                        "local_path": "/tmp/query-beta.jpg",
                        "query": "beta sneaker",
                        "query_group": "discord_noise",
                    },
                ],
            },
        ]
    }

    report = run_benchmark(manifest, strategy=DummyStrategy(), top_k=3)

    assert report["strategy"] == "dummy"
    assert report["dataset"] == {"products": 2, "catalog_images": 3, "queries": 2}
    assert report["metrics"] == {
        "queries": 2,
        "hit_at_1_count": 2,
        "hit_at_1": 1.0,
        "hit_at_3_count": 2,
        "hit_at_3": 1.0,
        "mrr_at_5": 1.0,
    }
    assert report["manifest_meta"] == {
        "dataset_name": "tip-v2",
        "query_groups": ["clean_web", "discord_noise"],
    }
    assert report["query_group_metrics"] == {
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
            "hit_at_1_count": 1,
            "hit_at_1": 1.0,
            "hit_at_3_count": 1,
            "hit_at_3": 1.0,
            "mrr_at_5": 1.0,
        },
    }

    alpha_query = report["results"][0]
    assert alpha_query["expected_product_id"] == "1001"
    assert alpha_query["query_group"] == "clean_web"
    assert [item["product_id"] for item in alpha_query["ranked_products"][:2]] == ["1001", "1002"]
    assert alpha_query["ranked_products"][0]["image_path"] == "/tmp/a-1.jpg"

    beta_query = report["results"][1]
    assert beta_query["expected_product_id"] == "1002"
    assert beta_query["query_group"] == "discord_noise"
    assert [item["product_id"] for item in beta_query["ranked_products"][:2]] == ["1002", "1001"]

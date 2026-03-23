import unittest
from types import SimpleNamespace

from backend.live_retrieval import backfill_product_image_retrieval_cache
from backend.retrieval_cache_warmup import (
    get_backfill_limit,
    should_run_startup_cache_warmup,
)


class _FakeStrategy:
    cache_version = "test_v1"

    def build_catalog_cache_payload(self, record):
        return {
            "embedding": [0.1, 0.2, 0.3],
            "color_hist": None,
            "tokens": ["demo"],
            "cache_version": self.cache_version,
        }


class _FakeDb:
    def __init__(self):
        self.fetch_calls = []
        self.saved_ids = []

    def get_searchable_product_image_records(self, **kwargs):
        self.fetch_calls.append(kwargs)
        return [
            {
                "product_id": 1,
                "title": "demo",
                "english_title": "demo",
                "description": "",
                "shop_name": "shop",
                "image_path": "/tmp/a.jpg",
                "image_index": 0,
                "image_db_id": 10,
                "retrieval_cache_strategy": None,
                "retrieval_cache_version": None,
                "retrieval_embedding": None,
                "retrieval_color_hist": None,
                "retrieval_tokens": None,
            }
        ]

    def get_image_info_by_id(self, image_db_id):
        return {"id": image_db_id}

    def upsert_product_image_retrieval_cache(self, image_db_id, **kwargs):
        self.saved_ids.append(image_db_id)
        return True


class RetrievalCacheWarmupTestCase(unittest.TestCase):
    def test_backfill_only_requests_missing_records_with_limit(self):
        db = _FakeDb()

        summary = backfill_product_image_retrieval_cache(
            db,
            "siglip2_rerank",
            limit=25,
            strategy_factory=lambda _name: _FakeStrategy(),
        )

        self.assertEqual(
            db.fetch_calls,
            [
                {
                    "strategy_name": "siglip2_rerank",
                    "require_cache": False,
                    "only_missing_cache": True,
                    "limit": 25,
                }
            ],
        )
        self.assertEqual(summary["processed"], 1)
        self.assertEqual(db.saved_ids, [10])

    def test_startup_cache_warmup_disabled_without_flag(self):
        config = SimpleNamespace(
            RETRIEVAL_CACHE_STARTUP_WARMUP=False,
            RETRIEVAL_CACHE_STARTUP_LIMIT=200,
        )

        self.assertFalse(should_run_startup_cache_warmup(config, "siglip2_rerank"))
        self.assertEqual(get_backfill_limit(config, "RETRIEVAL_CACHE_STARTUP_LIMIT"), 200)
        self.assertIsNone(get_backfill_limit(SimpleNamespace(RETRIEVAL_CACHE_STARTUP_LIMIT=0), "RETRIEVAL_CACHE_STARTUP_LIMIT"))


if __name__ == "__main__":
    unittest.main()

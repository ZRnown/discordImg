import unittest
from types import SimpleNamespace

from backend.live_retrieval import backfill_product_image_retrieval_cache
from backend.retrieval_cache_warmup import (
    get_auto_backfill_limit,
    get_backfill_cooldown_seconds,
    get_backfill_limit,
    get_backfill_interval_seconds,
    reduce_backfill_limit_after_failure,
    should_continue_auto_backfill_burst,
    should_run_auto_backfill,
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

    def test_auto_backfill_defaults_to_enabled_for_persisted_cache_strategy(self):
        config = SimpleNamespace(
            RETRIEVAL_CACHE_AUTO_BACKFILL=True,
            RETRIEVAL_CACHE_AUTO_BATCH_LIMIT=48,
            RETRIEVAL_CACHE_AUTO_BACKFILL_INTERVAL=120,
        )

        self.assertTrue(should_run_auto_backfill(config, "siglip2_rerank"))
        self.assertEqual(get_auto_backfill_limit(config, default=24), 48)
        self.assertEqual(
            get_backfill_interval_seconds(config, "RETRIEVAL_CACHE_AUTO_BACKFILL_INTERVAL", 60),
            120,
        )

    def test_auto_backfill_helpers_clamp_invalid_values(self):
        config = SimpleNamespace(
            RETRIEVAL_CACHE_AUTO_BACKFILL="yes",
            RETRIEVAL_CACHE_AUTO_BATCH_LIMIT=0,
            RETRIEVAL_CACHE_AUTO_BACKFILL_INTERVAL="bad",
            RETRIEVAL_CACHE_AUTO_BATCH_COOLDOWN=0,
        )

        self.assertTrue(should_run_auto_backfill(config, "siglip2_rerank"))
        self.assertEqual(get_auto_backfill_limit(config, default=24), 24)
        self.assertEqual(
            get_backfill_interval_seconds(config, "RETRIEVAL_CACHE_AUTO_BACKFILL_INTERVAL", 90),
            90,
        )
        self.assertEqual(
            get_backfill_cooldown_seconds(config, "RETRIEVAL_CACHE_AUTO_BATCH_COOLDOWN", 3),
            1,
        )
        self.assertEqual(reduce_backfill_limit_after_failure(48), 24)
        self.assertEqual(reduce_backfill_limit_after_failure(1), 1)

    def test_burst_backfill_only_continues_when_batch_made_progress_and_backlog_remains(self):
        self.assertTrue(
            should_continue_auto_backfill_burst({"processed": 24, "failed": 0}, remaining_count=100)
        )
        self.assertFalse(
            should_continue_auto_backfill_burst({"processed": 0, "failed": 24}, remaining_count=100)
        )
        self.assertFalse(
            should_continue_auto_backfill_burst({"processed": 24, "failed": 0}, remaining_count=0)
        )


if __name__ == "__main__":
    unittest.main()

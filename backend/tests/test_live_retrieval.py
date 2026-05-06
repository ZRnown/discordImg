import json
from collections import OrderedDict
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from backend.benchmarks.strategies import (
    Siglip2RerankStrategy,
    _coerce_siglip_embedding,
)
from backend.live_retrieval import (
    LiveCatalogImageRecord,
    LiveCatalogPreparingError,
    LiveImageRetriever,
    LiveProductSupportRecord,
    LiveQueryRecord,
    backfill_product_image_retrieval_cache,
    build_external_product_support_queries,
    build_catalog_record,
    _parse_json_float_array,
    build_query_record,
    build_catalog_records,
    load_runtime_product_support_records,
    prepare_catalog_entries,
    rank_query_products,
    refresh_external_product_support_assets,
)


class DummyLiveStrategy:
    name = "dummy_live"

    def prepare_catalog_image(self, record):
        return {
            "image_path": record.image_path,
        }

    def prepare_query_image(self, record):
        return {
            "query": record.query,
        }

    def score(self, query_context, catalog_context):
        query = query_context["query"]
        image_path = catalog_context["image_path"]
        score_map = {
            ("alpha runner", "/tmp/a-1.jpg"): 0.92,
            ("alpha runner", "/tmp/a-2.jpg"): 0.81,
            ("alpha runner", "/tmp/b-1.jpg"): 0.88,
            ("alpha runner", "/tmp/c-1.jpg"): 0.44,
        }
        return score_map.get((query, image_path), 0.0)


def test_build_external_product_support_queries_prefers_title_english_and_item_id():
    queries = build_external_product_support_queries(
        {
            "title": "Alpha Runner",
            "english_title": "Runner Alpha",
            "item_id": "w1001",
        },
        max_queries=4,
    )

    assert queries == [
        "Alpha Runner",
        "Runner Alpha",
        "Alpha Runner w1001",
        "Runner Alpha w1001",
    ]


def test_refresh_external_product_support_assets_reuses_existing_metadata_without_network(tmp_path):
    support_root = tmp_path / "support"
    product_dir = support_root / "1001"
    product_dir.mkdir(parents=True, exist_ok=True)
    support_image = product_dir / "support-a.jpg"
    Image.new("RGB", (96, 96), color=(80, 120, 160)).save(support_image)
    (product_dir / "metadata.json").write_text(
        json.dumps(
            {
                "product_id": "1001",
                "item_id": "w1001",
                "title": "Product A",
                "queries": ["alpha", "runner"],
                "images": [
                    {
                        "path": "support-a.jpg",
                        "source_url": "https://example.com/support-a.jpg",
                        "query": "alpha",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    class NoNetworkSession:
        def get(self, *_args, **_kwargs):
            raise AssertionError("should not fetch network when existing metadata already satisfies max_records")

    result = refresh_external_product_support_assets(
        {
            "id": "1001",
            "item_id": "w1001",
            "title": "Product A",
            "english_title": "Alpha Runner",
        },
        support_dir=support_root,
        session=NoNetworkSession(),
        max_queries=4,
        max_records=1,
        search_limit=4,
        per_query_limit=1,
    )

    assert result["product_id"] == "1001"
    assert result["saved"] == 0
    assert result["reused"] == 1
    assert result["total_images"] == 1
    assert result["queries"] == ["Product A", "Alpha Runner", "Product A w1001", "Alpha Runner w1001"]


def test_rank_query_products_aggregates_by_product_best_image():
    catalog = [
        LiveCatalogImageRecord(
            product_id="1001",
            title="Alpha Runner",
            english_title="",
            description="",
            shop_name="shop-a",
            image_path="/tmp/a-1.jpg",
            image_index=0,
            product_url="https://weidian.com/item.html?itemID=1001",
            queries=["alpha runner"],
        ),
        LiveCatalogImageRecord(
            product_id="1001",
            title="Alpha Runner",
            english_title="",
            description="",
            shop_name="shop-a",
            image_path="/tmp/a-2.jpg",
            image_index=1,
            product_url="https://weidian.com/item.html?itemID=1001",
            queries=["alpha runner"],
        ),
        LiveCatalogImageRecord(
            product_id="1002",
            title="Beta Runner",
            english_title="",
            description="",
            shop_name="shop-b",
            image_path="/tmp/b-1.jpg",
            image_index=0,
            product_url="https://weidian.com/item.html?itemID=1002",
            queries=["beta runner"],
        ),
    ]
    strategy = DummyLiveStrategy()
    prepared = prepare_catalog_entries(strategy, catalog)
    query = LiveQueryRecord(image_path="/tmp/query.jpg", query="alpha runner")

    ranked = rank_query_products(
        strategy=strategy,
        prepared_catalog=prepared,
        query_record=query,
        top_k=3,
    )

    assert [item["product_id"] for item in ranked] == ["1001", "1002"]
    assert ranked[0]["score"] == 0.92
    assert ranked[0]["image_path"] == "/tmp/a-1.jpg"
    assert ranked[1]["score"] == 0.88


def test_rank_query_products_respects_threshold_and_shop_scope():
    catalog = [
        LiveCatalogImageRecord(
            product_id="1001",
            title="Alpha Runner",
            english_title="",
            description="",
            shop_name="shop-a",
            image_path="/tmp/a-1.jpg",
            image_index=0,
            product_url="https://weidian.com/item.html?itemID=1001",
            queries=["alpha runner"],
        ),
        LiveCatalogImageRecord(
            product_id="1002",
            title="Beta Runner",
            english_title="",
            description="",
            shop_name="shop-b",
            image_path="/tmp/b-1.jpg",
            image_index=0,
            product_url="https://weidian.com/item.html?itemID=1002",
            queries=["beta runner"],
        ),
        LiveCatalogImageRecord(
            product_id="1003",
            title="Gamma Runner",
            english_title="",
            description="",
            shop_name="shop-c",
            image_path="/tmp/c-1.jpg",
            image_index=0,
            product_url="https://weidian.com/item.html?itemID=1003",
            queries=["gamma runner"],
        ),
    ]
    strategy = DummyLiveStrategy()
    prepared = prepare_catalog_entries(strategy, catalog)
    query = LiveQueryRecord(image_path="/tmp/query.jpg", query="alpha runner")

    ranked = rank_query_products(
        strategy=strategy,
        prepared_catalog=prepared,
        query_record=query,
        top_k=3,
        threshold=0.9,
        user_shops=["shop-a", "shop-b"],
    )

    assert [item["product_id"] for item in ranked] == ["1001"]


def test_rank_query_products_returns_empty_for_explicit_empty_shop_scope():
    catalog = [
        LiveCatalogImageRecord(
            product_id="1001",
            title="Alpha Runner",
            english_title="",
            description="",
            shop_name="shop-a",
            image_path="/tmp/a-1.jpg",
            image_index=0,
            product_url="https://weidian.com/item.html?itemID=1001",
            queries=["alpha runner"],
        ),
        LiveCatalogImageRecord(
            product_id="1002",
            title="Beta Runner",
            english_title="",
            description="",
            shop_name="shop-b",
            image_path="/tmp/b-1.jpg",
            image_index=0,
            product_url="https://weidian.com/item.html?itemID=1002",
            queries=["beta runner"],
        ),
    ]
    strategy = DummyLiveStrategy()
    prepared = prepare_catalog_entries(strategy, catalog)
    query = LiveQueryRecord(image_path="/tmp/query.jpg", query="alpha runner")

    ranked = rank_query_products(
        strategy=strategy,
        prepared_catalog=prepared,
        query_record=query,
        top_k=3,
        user_shops=[],
    )

    assert ranked == []


def test_rank_query_products_uses_vectorized_ranker_when_available(monkeypatch):
    calls = []

    class VectorizedStrategy:
        def prepare_query_image(self, record):
            return {"embedding": np.array([1.0, 0.0], dtype=np.float32)}

        def rank_products_fast(self, *, query_context, prepared_catalog, top_k):
            calls.append((len(prepared_catalog), top_k))
            return {
                "ranked_products": [
                    {
                        "product_id": "1001",
                        "title": "Alpha Runner",
                        "score": 0.97,
                        "image_path": "/tmp/a-1.jpg",
                        "image_index": 0,
                    }
                ]
            }

        def score(self, query_context, catalog_context):
            raise AssertionError("rank_query_products should use fast ranker before per-image score loop")

    prepared = [
        {
            "record": LiveCatalogImageRecord(
                product_id="1001",
                title="Alpha Runner",
                english_title="Alpha Runner",
                description="demo",
                shop_name="shop-a",
                image_path="/tmp/a-1.jpg",
                image_index=0,
                product_url="https://weidian.com/item.html?itemID=1001",
            ),
            "context": {"embedding": np.array([1.0, 0.0], dtype=np.float32)},
        },
        {
            "record": LiveCatalogImageRecord(
                product_id="1002",
                title="Beta Runner",
                english_title="Beta Runner",
                description="demo",
                shop_name="shop-b",
                image_path="/tmp/b-1.jpg",
                image_index=0,
                product_url="https://weidian.com/item.html?itemID=1002",
            ),
            "context": {"embedding": np.array([0.0, 1.0], dtype=np.float32)},
        },
    ]

    ranked = rank_query_products(
        strategy=VectorizedStrategy(),
        prepared_catalog=prepared,
        query_record=LiveQueryRecord(image_path="/tmp/query.jpg", query=""),
        top_k=1,
        threshold=0.5,
        user_shops=["shop-a"],
    )

    assert calls == [(1, 1)]
    assert [item["product_id"] for item in ranked] == ["1001"]
    assert ranked[0]["shop_name"] == "shop-a"


def test_siglip2_fast_rank_matches_standard_score_path(monkeypatch):
    monkeypatch.setenv("SIGLIP2_RERANK_PRODUCT_SUPPORT_ENABLED", "0")
    monkeypatch.setenv("SIGLIP2_RERANK_ADAPTIVE_RAW_CENTER", "0")
    monkeypatch.setenv("SIGLIP2_RERANK_QUERY_FUSION", "0")
    strategy = Siglip2RerankStrategy.__new__(Siglip2RerankStrategy)
    strategy.image_weight = 0.74
    strategy.color_weight = 0.11
    strategy.text_weight = 0.15
    strategy.category_weight = 0.0
    strategy.bonus_score = 0.05
    strategy.bonus_text_gate = 0.5
    strategy.bonus_image_gate = 0.5
    strategy.product_support_enabled = False
    strategy.adaptive_raw_center_enabled = False
    strategy.stage2_ridge_enabled = False
    strategy.stage2_hard_negative_enabled = False
    strategy.stage2_query_pair_enabled = False
    strategy.stage2_dynamic_cluster_enabled = False
    strategy.stage2_query_cluster_enabled = False
    strategy.stage2_targeted_support_enabled = False
    strategy.stage2_targeted_cluster_enabled = False
    strategy.stage2_targeted_pair_enabled = False
    strategy.stage2_support_stats_enabled = False
    strategy.query_fusion_enabled = False
    strategy.fast_rank_cache_scopes = 4
    strategy._fast_rank_cache = OrderedDict()
    strategy._fast_rank_cache_lock = type("NoopLock", (), {
        "__enter__": lambda self: self,
        "__exit__": lambda self, *_args: None,
    })()

    prepared = [
        {
            "record": LiveCatalogImageRecord(
                product_id="1001",
                title="Alpha",
                english_title="",
                description="",
                shop_name="shop-a",
                image_path="/tmp/a-1.jpg",
                image_index=0,
            ),
            "context": {
                "embedding": np.array([1.0, 0.0], dtype=np.float32),
                "hist": np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32),
                "tokens": {"alpha", "runner"},
                "category": "",
            },
        },
        {
            "record": LiveCatalogImageRecord(
                product_id="1002",
                title="Beta",
                english_title="",
                description="",
                shop_name="shop-a",
                image_path="/tmp/b-1.jpg",
                image_index=0,
            ),
            "context": {
                "embedding": np.array([0.0, 1.0], dtype=np.float32),
                "hist": np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32),
                "tokens": {"beta"},
                "category": "",
            },
        },
    ]
    query_context = {
        "embedding": np.array([1.0, 0.0], dtype=np.float32),
        "hist": np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32),
        "tokens": {"alpha"},
        "category": "",
    }

    fast_payload = strategy.rank_products_fast(
        query_context=query_context,
        prepared_catalog=prepared,
        top_k=2,
    )
    standard_rankings = [
        {
            "product_id": entry["record"].product_id,
            "title": entry["record"].title,
            "score": float(strategy.score(query_context, entry["context"])),
            "image_path": entry["record"].image_path,
            "image_index": entry["record"].image_index,
        }
        for entry in prepared
    ]
    standard_payload = {
        "ranked_products": strategy._rank_vectorized_product_scores(
            standard_rankings,
            top_k=2,
        )
    }

    assert fast_payload is not None
    assert [item["product_id"] for item in fast_payload["ranked_products"]] == ["1001", "1002"]
    assert np.allclose(
        [item["score"] for item in fast_payload["ranked_products"]],
        [item["score"] for item in standard_payload["ranked_products"]],
    )


def test_build_catalog_records_deserializes_siglip2_cache_fields():
    rows = [
        {
            "product_id": "1001",
            "title": "Alpha Runner",
            "english_title": "",
            "description": "",
            "shop_name": "shop-a",
            "image_path": "/tmp/a-1.jpg",
            "image_index": 0,
            "product_url": "https://weidian.com/item.html?itemID=1001",
            "retrieval_cache_strategy": "siglip2_rerank",
            "retrieval_cache_version": "siglip2_rerank_v1",
            "retrieval_embedding": "[0.1, 0.2, 0.3]",
            "retrieval_color_hist": "[0.4, 0.5, 0.6, 0.7]",
            "retrieval_tokens": "[\"alpha\", \"runner\"]",
        }
    ]

    records = build_catalog_records(rows)

    assert len(records) == 1
    assert records[0].cache_strategy_name == "siglip2_rerank"
    assert records[0].cache_version == "siglip2_rerank_v1"
    assert isinstance(records[0].cache_embedding, np.ndarray)
    assert np.allclose(records[0].cache_embedding, np.array([0.1, 0.2, 0.3], dtype=np.float32))
    assert isinstance(records[0].cache_color_hist, np.ndarray)
    assert np.allclose(records[0].cache_color_hist, np.array([0.4, 0.5, 0.6, 0.7], dtype=np.float32))
    assert records[0].cache_tokens == ["alpha", "runner"]


def test_build_catalog_record_preserves_cached_arrays_for_streaming_search():
    row = {
        "product_id": "1001",
        "title": "Alpha Runner",
        "english_title": "",
        "description": "",
        "shop_name": "shop-a",
        "image_path": "/tmp/a-1.jpg",
        "image_index": 0,
        "product_url": "https://weidian.com/item.html?itemID=1001",
        "retrieval_cache_strategy": "siglip2_rerank",
        "retrieval_cache_version": "siglip2_rerank_v1",
        "retrieval_embedding": "[0.1, 0.2, 0.3]",
        "retrieval_color_hist": "[0.4, 0.5, 0.6, 0.7]",
        "retrieval_tokens": "[\"alpha\", \"runner\"]",
    }

    record = build_catalog_record(row, preserve_cached_arrays=True)

    assert record is not None
    assert record.cache_embedding == "[0.1, 0.2, 0.3]"
    assert record.cache_color_hist == "[0.4, 0.5, 0.6, 0.7]"
    assert record.cache_tokens == ["alpha", "runner"]


def test_parse_json_float_array_uses_numpy_fast_path():
    parsed = _parse_json_float_array("[1.0,2.5,3.25]")

    assert isinstance(parsed, np.ndarray)
    assert parsed.dtype == np.float32
    assert np.allclose(parsed, np.array([1.0, 2.5, 3.25], dtype=np.float32))


def test_siglip2_cache_deserializers_accept_serialized_float_strings():
    embedding = _coerce_siglip_embedding("[3.0, 4.0]")
    hist = Siglip2RerankStrategy._deserialize_cached_hist("[0.1, 0.2, 0.3, 0.4]")

    assert embedding is not None
    assert np.allclose(embedding, np.array([0.6, 0.8], dtype=np.float32))
    assert hist is not None
    assert hist.dtype == np.float32
    assert hist.shape == (4,)
    assert np.allclose(hist, np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32))


def test_build_query_record_ignores_query_text_for_live_image_search():
    record = build_query_record("/tmp/query.jpg", query_text="Balenciaga hoodie")

    assert record.image_path == "/tmp/query.jpg"
    assert record.query == ""
    assert record.product_queries == []


def test_load_runtime_product_support_records_includes_external_support_in_auto_mode(
    tmp_path,
    monkeypatch,
):
    support_dir = tmp_path / "external-support" / "916"
    support_dir.mkdir(parents=True)
    support_image_path = support_dir / "support.jpg"
    Image.new("RGB", (96, 96), color=(255, 0, 0)).save(support_image_path, format="JPEG")
    (support_dir / "metadata.json").write_text(
        json.dumps(
            {
                "product_id": "916",
                "item_id": "7713998250",
                "title": "Alpha Runner",
                "queries": ["alpha runner"],
                "images": [{"path": "support.jpg"}],
            }
        ),
        encoding="utf-8",
    )
    catalog_image_path = tmp_path / "catalog.jpg"
    Image.new("RGB", (96, 96), color=(0, 255, 0)).save(catalog_image_path, format="JPEG")

    monkeypatch.setenv("LIVE_IMAGE_SEARCH_PRODUCT_SUPPORT_MODE", "auto")
    monkeypatch.setenv("LIVE_IMAGE_SEARCH_EXTERNAL_PRODUCT_SUPPORT_ENABLED", "1")
    monkeypatch.setenv("LIVE_IMAGE_SEARCH_EXTERNAL_PRODUCT_SUPPORT_DIR", str(tmp_path / "external-support"))
    monkeypatch.setenv("LIVE_IMAGE_SEARCH_AUTO_PRODUCT_SUPPORT_ENABLED", "0")
    monkeypatch.delenv("LIVE_IMAGE_SEARCH_PRODUCT_SUPPORT_MANIFEST", raising=False)

    records = load_runtime_product_support_records(
        [
            LiveCatalogImageRecord(
                product_id="916",
                item_id="7713998250",
                title="Alpha Runner",
                english_title="",
                description="",
                shop_name="shop-a",
                image_path=str(catalog_image_path),
                image_index=0,
            )
        ]
    )

    assert len(records) == 1
    assert records[0].expected_product_id == "916"
    assert Path(records[0].image_path) == support_image_path


def test_load_runtime_product_support_records_skips_materializing_missing_auto_variants_by_default(
    tmp_path,
    monkeypatch,
):
    output_dir = tmp_path / "auto-support"
    catalog_image_path = tmp_path / "catalog.jpg"
    Image.new("RGB", (96, 96), color=(0, 255, 0)).save(catalog_image_path, format="JPEG")

    monkeypatch.setenv("LIVE_IMAGE_SEARCH_PRODUCT_SUPPORT_MODE", "auto")
    monkeypatch.setenv("LIVE_IMAGE_SEARCH_EXTERNAL_PRODUCT_SUPPORT_ENABLED", "0")
    monkeypatch.setenv("LIVE_IMAGE_SEARCH_AUTO_PRODUCT_SUPPORT_ENABLED", "1")
    monkeypatch.setenv("LIVE_IMAGE_SEARCH_AUTO_PRODUCT_SUPPORT_DIR", str(output_dir))
    monkeypatch.delenv("LIVE_IMAGE_SEARCH_PRODUCT_SUPPORT_MANIFEST", raising=False)

    records = load_runtime_product_support_records(
        [
            LiveCatalogImageRecord(
                product_id="916",
                item_id="7713998250",
                title="Alpha Runner",
                english_title="",
                description="",
                shop_name="shop-a",
                image_path=str(catalog_image_path),
                image_index=0,
            )
        ]
    )

    assert len(records) == 1
    assert Path(records[0].image_path) == catalog_image_path
    assert list(output_dir.rglob("*")) == []


def test_prepare_catalog_entries_reuses_catalog_context_for_matching_support_images():
    class SupportReuseStrategy:
        def __init__(self):
            self.prepare_calls = []
            self.support_contexts = []

        def prepare_catalog_image(self, record):
            context = {
                "image_path": record.image_path,
                "call_index": len(self.prepare_calls),
            }
            self.prepare_calls.append(record.image_path)
            return context

        def set_product_support_records(self, support_records, prepared_catalog=None):
            prepared_by_path = {
                entry["record"].image_path: entry["context"]
                for entry in (prepared_catalog or [])
            }
            self.support_contexts = []
            for record in support_records:
                context = prepared_by_path.get(record.image_path)
                if context is None:
                    context = self.prepare_catalog_image(record)
                self.support_contexts.append(context)

        def prepare_query_image(self, record):
            return {"query": record.query}

        def score(self, query_context, catalog_context):
            return 1.0

    catalog = [
        LiveCatalogImageRecord(
            product_id="1001",
            title="Alpha Runner",
            english_title="",
            description="",
            shop_name="shop-a",
            image_path="/tmp/a-1.jpg",
            image_index=0,
            product_url="https://weidian.com/item.html?itemID=1001",
            queries=["alpha runner"],
        ),
    ]
    support_records = [
        LiveProductSupportRecord(
            expected_product_id="1001",
            image_path="/tmp/a-1.jpg",
            title="Alpha Runner",
            product_queries=["alpha runner"],
        )
    ]
    strategy = SupportReuseStrategy()

    prepared = prepare_catalog_entries(
        strategy,
        catalog,
        support_records=support_records,
    )

    assert strategy.prepare_calls == ["/tmp/a-1.jpg"]
    assert strategy.support_contexts == [prepared[0]["context"]]


def test_backfill_product_image_retrieval_cache_only_persists_missing_rows():
    class FakeDB:
        def __init__(self):
            self.upserts = []

        def get_searchable_product_image_records(self, **kwargs):
            assert kwargs["strategy_name"] == "siglip2_rerank"
            assert kwargs["require_cache"] is False
            assert kwargs["only_missing_cache"] is True
            assert kwargs["limit"] is None
            return [
                {
                    "product_id": "1001",
                    "title": "Alpha Runner",
                    "image_db_id": 11,
                    "image_path": "/tmp/a-1.jpg",
                    "image_index": 0,
                    "retrieval_cache_strategy": None,
                },
                {
                    "product_id": "1002",
                    "title": "Beta Runner",
                    "image_db_id": 12,
                    "image_path": "/tmp/b-1.jpg",
                    "image_index": 0,
                    "retrieval_cache_strategy": "siglip2_rerank",
                },
            ]

        def upsert_product_image_retrieval_cache(self, **kwargs):
            self.upserts.append(kwargs)
            return True

    class FakeStrategy:
        name = "siglip2_rerank"
        cache_version = "siglip2_rerank_v1"

        def build_catalog_cache_payload(self, record):
            return {
                "embedding": [0.1, 0.2, 0.3],
                "color_hist": [0.4, 0.5, 0.6, 0.7],
                "tokens": ["alpha", "runner"],
                "cache_version": self.cache_version,
            }

    fake_db = FakeDB()

    result = backfill_product_image_retrieval_cache(
        db_handle=fake_db,
        strategy_name="siglip2_rerank",
        strategy_factory=lambda _name: FakeStrategy(),
    )

    assert result["processed"] == 1
    assert result["skipped"] == 1
    assert len(fake_db.upserts) == 1
    assert fake_db.upserts[0]["image_db_id"] == 11
    assert fake_db.upserts[0]["strategy_name"] == "siglip2_rerank"


def test_backfill_product_image_retrieval_cache_skips_deleted_rows_and_empty_embeddings():
    class FakeDB:
        def __init__(self):
            self.upserts = []

        def get_searchable_product_image_records(self, **kwargs):
            assert kwargs["strategy_name"] == "siglip2_rerank"
            assert kwargs["require_cache"] is False
            assert kwargs["only_missing_cache"] is True
            assert kwargs["limit"] is None
            return [
                {
                    "product_id": "1001",
                    "title": "Ghost Runner",
                    "image_db_id": 11,
                    "image_path": "/tmp/gone.jpg",
                    "image_index": 0,
                    "retrieval_cache_strategy": None,
                },
                {
                    "product_id": "1002",
                    "title": "Broken Runner",
                    "image_db_id": 12,
                    "image_path": "/tmp/broken.jpg",
                    "image_index": 0,
                    "retrieval_cache_strategy": None,
                },
            ]

        def get_image_info_by_id(self, image_db_id):
            if image_db_id == 11:
                return None
            return {"id": image_db_id}

        def upsert_product_image_retrieval_cache(self, **kwargs):
            self.upserts.append(kwargs)
            return True

    class FakeStrategy:
        name = "siglip2_rerank"
        cache_version = "siglip2_rerank_v1"

        def build_catalog_cache_payload(self, record):
            assert record.image_db_id == 12
            return {
                "embedding": None,
                "color_hist": [0.4, 0.5],
                "tokens": ["broken"],
                "cache_version": self.cache_version,
            }

    fake_db = FakeDB()

    result = backfill_product_image_retrieval_cache(
        db_handle=fake_db,
        strategy_name="siglip2_rerank",
        strategy_factory=lambda _name: FakeStrategy(),
    )

    assert result["processed"] == 0
    assert result["skipped"] == 1
    assert result["failed"] == 1
    assert fake_db.upserts == []


def test_live_image_retriever_reuses_prepared_catalog_without_reloading_rows(monkeypatch):
    class FakeDB:
        def __init__(self):
            self.calls = 0

        def get_searchable_product_image_records(self, **kwargs):
            self.calls += 1
            return [
                {
                    "product_id": "1001",
                    "title": "Alpha Runner",
                    "english_title": "Alpha Runner",
                    "description": "",
                    "shop_name": "shop-a",
                    "image_path": "/tmp/a-1.jpg",
                    "image_index": 0,
                    "product_url": "https://weidian.com/item.html?itemID=1001",
                    "retrieval_cache_strategy": "siglip2_rerank",
                    "retrieval_cache_version": "siglip2_rerank_v1",
                    "retrieval_embedding": "[0.1, 0.2, 0.3]",
                    "retrieval_color_hist": None,
                    "retrieval_tokens": "[\"alpha\", \"runner\"]",
                }
            ]

    class FakeStrategy:
        def prepare_catalog_image(self, record):
            return {"image_path": record.image_path}

        def prepare_query_image(self, record):
            return {"query": record.query}

        def score(self, query_context, catalog_context):
            return 0.95

    monkeypatch.setattr(
        "backend.benchmarks.strategies.create_strategy",
        lambda _name: FakeStrategy(),
    )

    retriever = LiveImageRetriever(FakeDB(), "siglip2_rerank")
    retriever.warm()
    first = retriever.search("/tmp/query-a.jpg", query_text="alpha", top_k=1, threshold=0.0)
    second = retriever.search("/tmp/query-b.jpg", query_text="alpha", top_k=1, threshold=0.0)

    assert first["catalog_size"] == 1
    assert second["catalog_size"] == 1
    assert retriever.db.calls == 1


def test_live_image_retriever_warm_prepares_catalog_before_search(monkeypatch):
    class FakeDB:
        def __init__(self):
            self.calls = 0

        def get_searchable_product_image_records(self, **kwargs):
            self.calls += 1
            return [
                {
                    "product_id": "1001",
                    "title": "Alpha Runner",
                    "english_title": "Alpha Runner",
                    "description": "",
                    "shop_name": "shop-a",
                    "image_path": "/tmp/a-1.jpg",
                    "image_index": 0,
                    "product_url": "https://weidian.com/item.html?itemID=1001",
                    "retrieval_cache_strategy": "siglip2_rerank",
                    "retrieval_cache_version": "siglip2_rerank_v1",
                    "retrieval_embedding": "[0.1, 0.2, 0.3]",
                    "retrieval_color_hist": None,
                    "retrieval_tokens": "[\"alpha\", \"runner\"]",
                }
            ]

    class FakeStrategy:
        def prepare_catalog_image(self, record):
            return {"image_path": record.image_path}

        def prepare_query_image(self, record):
            return {"query": record.query}

        def score(self, query_context, catalog_context):
            return 0.95

    monkeypatch.setattr(
        "backend.benchmarks.strategies.create_strategy",
        lambda _name: FakeStrategy(),
    )

    retriever = LiveImageRetriever(FakeDB(), "siglip2_rerank")

    warm_summary = retriever.warm()
    result = retriever.search("/tmp/query-a.jpg", query_text="alpha", top_k=1, threshold=0.0)

    assert warm_summary["catalog_size"] == 1
    assert result["catalog_size"] == 1
    assert retriever.db.calls == 1


def test_live_image_retriever_cold_search_starts_background_prepare_and_raises_not_ready(monkeypatch):
    class FakeStrategy:
        def supports_streaming_live_search(self):
            return False

    monkeypatch.setattr(
        "backend.live_retrieval.get_retrieval_strategy_instance",
        lambda *args, **kwargs: FakeStrategy(),
    )

    class FakeDB:
        pass

    retriever = LiveImageRetriever(FakeDB(), "siglip2_rerank")
    started = []

    def fake_start_background_refresh_locked():
        started.append(True)
        retriever._prepare_inflight = True
        return True

    monkeypatch.setattr(
        retriever,
        "_start_background_refresh_locked",
        fake_start_background_refresh_locked,
    )

    with pytest.raises(LiveCatalogPreparingError):
        retriever.search("/tmp/query.jpg", top_k=1, threshold=0.0)

    assert started == [True]


def test_live_image_retriever_search_keeps_using_previous_catalog_while_refreshing(monkeypatch):
    class FakeDB:
        def __init__(self):
            self.calls = 0

        def get_searchable_product_image_records(self, **kwargs):
            self.calls += 1
            product_id = "1001" if self.calls == 1 else "2002"
            image_path = "/tmp/a-1.jpg" if self.calls == 1 else "/tmp/b-1.jpg"
            title = "Alpha Runner" if self.calls == 1 else "Beta Runner"
            return [
                {
                    "product_id": product_id,
                    "title": title,
                    "english_title": title,
                    "description": "",
                    "shop_name": "shop-a",
                    "image_path": image_path,
                    "image_index": 0,
                    "product_url": f"https://weidian.com/item.html?itemID={product_id}",
                    "retrieval_cache_strategy": "siglip2_rerank",
                    "retrieval_cache_version": "siglip2_rerank_v1",
                    "retrieval_embedding": "[0.1, 0.2, 0.3]",
                    "retrieval_color_hist": None,
                    "retrieval_tokens": "[\"alpha\", \"runner\"]",
                }
            ]

    class FakeStrategy:
        def prepare_catalog_image(self, record):
            return {"image_path": record.image_path}

        def prepare_query_image(self, record):
            return {"query": record.query}

        def score(self, query_context, catalog_context):
            return 0.95 if catalog_context["image_path"] == "/tmp/a-1.jpg" else 0.11

    monkeypatch.setattr(
        "backend.benchmarks.strategies.create_strategy",
        lambda _name: FakeStrategy(),
    )

    retriever = LiveImageRetriever(FakeDB(), "siglip2_rerank")
    retriever.warm()
    first = retriever.search("/tmp/query-a.jpg", query_text="alpha", top_k=1, threshold=0.0)

    started = []

    def fake_start_background_refresh_locked():
        started.append(True)
        retriever._prepare_inflight = True
        return True

    monkeypatch.setattr(
        retriever,
        "_start_background_refresh_locked",
        fake_start_background_refresh_locked,
    )

    retriever.invalidate()
    second = retriever.search("/tmp/query-b.jpg", query_text="alpha", top_k=1, threshold=0.0)

    assert first["ranked_products"][0]["product_id"] == "1001"
    assert second["ranked_products"][0]["product_id"] == "1001"
    assert retriever.db.calls == 1
    assert started == [True]


def test_live_image_retriever_search_prefers_prepared_catalog_by_default(monkeypatch):
    class FakeDB:
        def __init__(self):
            self.materialized_calls = []

        def get_searchable_product_image_records(self, **kwargs):
            self.materialized_calls.append(kwargs)
            return [
                {
                    "product_id": "2001",
                    "title": "Allowed Alpha",
                    "english_title": "Allowed Alpha",
                    "description": "demo",
                    "shop_name": "shop-allowed",
                    "image_path": "/tmp/allowed.jpg",
                    "image_index": 0,
                    "product_url": "https://weidian.com/item.html?itemID=2001",
                    "retrieval_cache_strategy": "siglip2_rerank",
                    "retrieval_cache_version": "siglip2_rerank_v1",
                    "retrieval_embedding": "[0.1, 0.2, 0.3]",
                    "retrieval_color_hist": None,
                    "retrieval_tokens": "[\"alpha\"]",
                }
            ]

        def iter_searchable_product_image_records(self, **kwargs):
            raise AssertionError("default live search should not stream-scan the catalog")

    class FakeStrategy:
        def supports_streaming_live_search(self):
            return True

        def prepare_query_image(self, record):
            return {"query": record.query}

        def prepare_catalog_image(self, record):
            if record.product_id == "2001":
                assert record.cache_embedding == [0.1, 0.2, 0.3]
            return {"score": 0.93 if record.product_id == "2001" else 0.11}

        def score(self, query_context, catalog_context):
            return catalog_context["score"]

    monkeypatch.setattr(
        "backend.benchmarks.strategies.create_strategy",
        lambda _name: FakeStrategy(),
    )

    retriever = LiveImageRetriever(FakeDB(), "siglip2_rerank")
    retriever.warm()
    result = retriever.search(
        "/tmp/query.jpg",
        query_text="ignored",
        top_k=3,
        threshold=0.2,
        user_shops=["shop-allowed"],
    )

    assert result["catalog_size"] == 1
    assert [item["product_id"] for item in result["ranked_products"]] == ["2001"]
    assert retriever.db.materialized_calls == [
        {
            "strategy_name": "siglip2_rerank",
            "require_cache": True,
        }
    ]


def test_live_image_retriever_reuses_scoped_catalog_for_same_shop_scope(monkeypatch):
    class FakeDB:
        def __init__(self):
            self.materialized_calls = []

        def get_searchable_product_image_records(self, **kwargs):
            self.materialized_calls.append(kwargs)
            shop_names = kwargs.get("shop_names") or []
            assert shop_names
            shop_name = shop_names[0]
            return [
                {
                    "product_id": "2001",
                    "title": "Allowed Alpha",
                    "english_title": "Allowed Alpha",
                    "description": "demo",
                    "shop_name": shop_name,
                    "image_path": "/tmp/allowed.jpg",
                    "image_index": 0,
                    "product_url": "https://weidian.com/item.html?itemID=2001",
                    "retrieval_cache_strategy": "siglip2_rerank",
                    "retrieval_cache_version": "siglip2_rerank_v1",
                    "retrieval_embedding": "[0.1, 0.2, 0.3]",
                    "retrieval_color_hist": None,
                    "retrieval_tokens": "[\"alpha\"]",
                }
            ]

    class FakeStrategy:
        def supports_streaming_live_search(self):
            return False

        def prepare_query_image(self, record):
            return {"query": record.query}

        def prepare_catalog_image(self, record):
            return {"score": 0.93}

        def score(self, query_context, catalog_context):
            return catalog_context["score"]

    monkeypatch.setattr(
        "backend.live_retrieval.get_retrieval_strategy_instance",
        lambda *args, **kwargs: FakeStrategy(),
    )

    retriever = LiveImageRetriever(FakeDB(), "siglip2_rerank")
    first = retriever.search(
        "/tmp/query-a.jpg",
        query_text="ignored",
        top_k=3,
        threshold=0.2,
        user_shops=["shop-allowed"],
    )
    second = retriever.search(
        "/tmp/query-b.jpg",
        query_text="ignored",
        top_k=3,
        threshold=0.2,
        user_shops=["shop-allowed"],
    )

    assert [item["product_id"] for item in first["ranked_products"]] == ["2001"]
    assert [item["product_id"] for item in second["ranked_products"]] == ["2001"]
    assert retriever.db.materialized_calls == [
        {
            "strategy_name": "siglip2_rerank",
            "require_cache": True,
            "shop_names": ("shop-allowed",),
            "ordered": False,
        }
    ]


def test_live_image_retriever_loads_scoped_catalog_from_disk_cache(tmp_path, monkeypatch):
    class FakeDB:
        def __init__(self):
            self.materialized_calls = []

        def get_searchable_product_image_records_signature(self, **kwargs):
            return {
                "count": 1,
                "max_image_db_id": 11,
                "max_product_id": 2001,
                "max_product_updated_at": "2026-05-06 00:00:00",
                "max_cache_updated_at": "2026-05-06 00:00:01",
            }

        def get_searchable_product_image_records(self, **kwargs):
            self.materialized_calls.append(kwargs)
            return [
                {
                    "product_id": "2001",
                    "title": "Allowed Alpha",
                    "english_title": "Allowed Alpha",
                    "description": "demo",
                    "shop_name": "shop-allowed",
                    "image_path": "/tmp/allowed.jpg",
                    "image_index": 0,
                    "product_url": "https://weidian.com/item.html?itemID=2001",
                    "retrieval_cache_strategy": "siglip2_rerank",
                    "retrieval_cache_version": "siglip2_rerank_v1",
                    "retrieval_embedding": "[0.1, 0.2, 0.3]",
                    "retrieval_color_hist": None,
                    "retrieval_tokens": "[\"alpha\"]",
                }
            ]

    class FakeStrategy:
        def supports_streaming_live_search(self):
            return False

        def prepare_query_image(self, record):
            return {"query": record.query}

        def prepare_catalog_image(self, record):
            return {"score": 0.93}

        def score(self, query_context, catalog_context):
            return catalog_context["score"]

    monkeypatch.setenv("LIVE_IMAGE_SEARCH_SCOPED_CATALOG_DISK_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(
        "backend.live_retrieval.get_retrieval_strategy_instance",
        lambda *args, **kwargs: FakeStrategy(),
    )

    first_db = FakeDB()
    first_retriever = LiveImageRetriever(first_db, "siglip2_rerank")
    first = first_retriever.search(
        "/tmp/query-a.jpg",
        top_k=1,
        threshold=0.0,
        user_shops=["shop-allowed"],
    )

    second_db = FakeDB()
    second_retriever = LiveImageRetriever(second_db, "siglip2_rerank")
    second = second_retriever.search(
        "/tmp/query-b.jpg",
        top_k=1,
        threshold=0.0,
        user_shops=["shop-allowed"],
    )

    assert [item["product_id"] for item in first["ranked_products"]] == ["2001"]
    assert [item["product_id"] for item in second["ranked_products"]] == ["2001"]
    assert len(list(tmp_path.glob("*.pkl"))) == 1
    assert len(first_db.materialized_calls) == 1
    assert second_db.materialized_calls == []


def test_live_image_retriever_warm_skips_streaming_catalog_count(monkeypatch):
    class FakeDB:
        def __init__(self):
            self.count_calls = []

        def get_searchable_product_image_records(self, **kwargs):
            raise AssertionError("warm should not materialize the full catalog in streaming mode")

        def count_searchable_product_image_records(self, **kwargs):
            self.count_calls.append(kwargs)
            return 42

    class FakeStrategy:
        def supports_streaming_live_search(self):
            return True

    monkeypatch.setenv("LIVE_IMAGE_SEARCH_STREAMING_ENABLED", "1")
    monkeypatch.setenv("LIVE_IMAGE_SEARCH_STREAMING_FORCE", "1")
    monkeypatch.setattr(
        "backend.live_retrieval.get_retrieval_strategy_instance",
        lambda *args, **kwargs: FakeStrategy(),
    )

    retriever = LiveImageRetriever(FakeDB(), "siglip2_rerank")

    warm_summary = retriever.warm()

    assert warm_summary == {
        "strategy": "siglip2_rerank",
        "catalog_size": 0,
        "streaming": True,
        "skipped_count": True,
    }
    assert retriever.db.count_calls == []


def test_live_image_retriever_streaming_search_requires_explicit_enable(monkeypatch):
    class FakeDB:
        def __init__(self):
            self.iter_calls = []

        def get_searchable_product_image_records(self, **kwargs):
            raise AssertionError("streaming mode should avoid materializing the full catalog")

        def iter_searchable_product_image_records(self, **kwargs):
            self.iter_calls.append(kwargs)
            yield {
                "product_id": "2001",
                "title": "Allowed Alpha",
                "english_title": "Allowed Alpha",
                "description": "demo",
                "shop_name": "shop-allowed",
                "image_path": "/tmp/allowed.jpg",
                "image_index": 0,
                "product_url": "https://weidian.com/item.html?itemID=2001",
                "retrieval_cache_strategy": "siglip2_rerank",
                "retrieval_cache_version": "siglip2_rerank_v1",
                "retrieval_embedding": "[0.1, 0.2, 0.3]",
                "retrieval_color_hist": None,
                "retrieval_tokens": "[\"alpha\"]",
            }

    class FakeStrategy:
        def supports_streaming_live_search(self):
            return True

        def prepare_query_image(self, record):
            return {"query": record.query}

        def prepare_catalog_image(self, record):
            return {"score": 0.93}

        def score(self, query_context, catalog_context):
            return catalog_context["score"]

    monkeypatch.setenv("LIVE_IMAGE_SEARCH_STREAMING_ENABLED", "1")
    monkeypatch.setenv("LIVE_IMAGE_SEARCH_STREAMING_FORCE", "1")
    monkeypatch.setattr(
        "backend.live_retrieval.get_retrieval_strategy_instance",
        lambda *args, **kwargs: FakeStrategy(),
    )

    retriever = LiveImageRetriever(FakeDB(), "siglip2_rerank")

    result = retriever.search(
        "/tmp/query.jpg",
        query_text="ignored",
        top_k=3,
        threshold=0.2,
        user_shops=["shop-allowed"],
    )

    assert result["catalog_size"] == 1
    assert [item["product_id"] for item in result["ranked_products"]] == ["2001"]
    assert retriever.db.iter_calls == [
        {
            "strategy_name": "siglip2_rerank",
            "require_cache": True,
            "only_missing_cache": False,
            "limit": None,
            "shop_names": ["shop-allowed"],
            "ordered": False,
        }
    ]

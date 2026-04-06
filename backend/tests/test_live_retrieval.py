import json
from pathlib import Path

from PIL import Image

from backend.live_retrieval import (
    LiveCatalogImageRecord,
    LiveImageRetriever,
    LiveProductSupportRecord,
    LiveQueryRecord,
    backfill_product_image_retrieval_cache,
    build_query_record,
    build_catalog_records,
    load_runtime_product_support_records,
    prepare_catalog_entries,
    rank_query_products,
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
    assert records[0].cache_embedding == [0.1, 0.2, 0.3]
    assert records[0].cache_color_hist == [0.4, 0.5, 0.6, 0.7]
    assert records[0].cache_tokens == ["alpha", "runner"]


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

    first = retriever.search("/tmp/query-a.jpg", query_text="alpha", top_k=1, threshold=0.0)
    second = retriever.search("/tmp/query-b.jpg", query_text="alpha", top_k=1, threshold=0.0)

    assert first["catalog_size"] == 1
    assert second["catalog_size"] == 1
    assert retriever.db.calls == 1

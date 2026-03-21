from backend.live_retrieval import (
    LiveCatalogImageRecord,
    LiveQueryRecord,
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

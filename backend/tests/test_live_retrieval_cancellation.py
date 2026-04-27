import sys
import threading
import types
import unittest
from types import SimpleNamespace

if "PIL" not in sys.modules:
    pil_module = types.ModuleType("PIL")
    pil_module.Image = object()
    pil_module.ImageFilter = object()
    sys.modules["PIL"] = pil_module

from backend.live_retrieval import _rank_products_for_query, rank_query_products


class LiveRetrievalCancellationTestCase(unittest.TestCase):
    def test_rank_query_products_returns_immediately_when_cancelled_before_start(self):
        cancel_event = threading.Event()
        cancel_event.set()

        class FakeStrategy:
            def __init__(self):
                self.prepare_query_calls = 0

            def prepare_query_image(self, query_record):
                self.prepare_query_calls += 1
                return {"query_path": query_record.image_path}

            def score(self, query_context, catalog_context):
                return 0.99

        strategy = FakeStrategy()
        query_record = SimpleNamespace(image_path="/tmp/query.jpg", query="")

        result = rank_query_products(
            strategy=strategy,
            prepared_catalog=[],
            query_record=query_record,
            cancel_event=cancel_event,
        )

        self.assertEqual(result, [])
        self.assertEqual(strategy.prepare_query_calls, 0)

    def test_rank_products_for_query_stops_after_cancel_event_is_set(self):
        cancel_event = threading.Event()

        class FakeStrategy:
            def __init__(self):
                self.score_calls = 0

            def score(self, query_context, catalog_context):
                self.score_calls += 1
                if self.score_calls == 1:
                    cancel_event.set()
                return 0.9

        strategy = FakeStrategy()
        prepared_catalog = [
            {
                "record": SimpleNamespace(
                    product_id="p1",
                    title="Product 1",
                    image_path="/tmp/1.jpg",
                    image_index=1,
                    shop_name="shop-a",
                ),
                "context": {"image": 1},
            },
            {
                "record": SimpleNamespace(
                    product_id="p2",
                    title="Product 2",
                    image_path="/tmp/2.jpg",
                    image_index=2,
                    shop_name="shop-a",
                ),
                "context": {"image": 2},
            },
        ]

        result = _rank_products_for_query(
            strategy=strategy,
            prepared_catalog=prepared_catalog,
            query_context={"query": "image"},
            top_k=5,
            cancel_event=cancel_event,
        )

        self.assertEqual(strategy.score_calls, 1)
        self.assertEqual(len(result["ranked_products"]), 1)
        self.assertEqual(result["ranked_products"][0]["product_id"], "p1")


if __name__ == "__main__":
    unittest.main()

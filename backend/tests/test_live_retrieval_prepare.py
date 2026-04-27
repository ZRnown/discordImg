import sys
import types
import unittest

fake_pil_module = types.ModuleType("PIL")
fake_pil_module.Image = object()
fake_pil_module.ImageFilter = object()
sys.modules.setdefault("PIL", fake_pil_module)

from backend.live_retrieval import LiveImageRetriever


class LiveImageRetrieverPrepareTestCase(unittest.TestCase):
    def test_ensure_prepared_catalog_builds_sync_when_no_active_catalog(self):
        retriever = LiveImageRetriever(db_handle=object(), strategy_name="siglip2_rerank")
        expected_strategy = object()
        expected_catalog = [{"record": object(), "context": object()}]
        expected_signature = ("sig",)

        def _build_snapshot():
            return expected_strategy, expected_catalog, expected_signature

        retriever._build_prepared_catalog_snapshot = _build_snapshot  # type: ignore[method-assign]

        strategy, catalog = retriever._ensure_prepared_catalog()

        self.assertIs(strategy, expected_strategy)
        self.assertIs(catalog, expected_catalog)
        self.assertEqual(retriever._catalog_signature, expected_signature)


if __name__ == "__main__":
    unittest.main()

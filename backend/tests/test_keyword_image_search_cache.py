import unittest

from backend.keyword_image_search import KeywordImageSearchService


class KeywordImageSearchCacheTest(unittest.TestCase):
    def test_reuses_external_and_internal_results_for_same_keyword_image_scope(self):
        service = KeywordImageSearchService()
        external_calls = []
        internal_calls = []

        def fake_external(query_text, max_images, *, credentials):
            external_calls.append((query_text, max_images, credentials["provider"]))
            return [
                {
                    "image_url": "https://example.test/image.jpg",
                    "page_url": "https://example.test/page",
                    "title": "Example",
                    "thumbnail_url": "https://example.test/thumb.jpg",
                }
            ]

        def fake_internal(**kwargs):
            internal_calls.append(kwargs)
            return {
                "similarity": 0.91,
                "product": {
                    "id": 123,
                    "weidianUrl": "https://weidian.com/item.html?itemID=778899",
                },
            }

        service._search_searchapi_google_images = fake_external
        service._search_internal_by_image = fake_internal

        website_config = {
            "url_template": "https://shop.example/item/{id}",
            "image_similarity_threshold": 0.8,
        }
        user_settings = {
            "keyword_image_search_provider": "searchapi_google_images",
            "keyword_image_search_api_key": "test-key",
        }

        first = service.search_candidates(
            query_text="same product",
            website_config=website_config,
            user_id=7,
            user_shops=["shop-a"],
            max_images=3,
            user_settings=user_settings,
        )
        second = service.search_candidates(
            query_text="same product",
            website_config=website_config,
            user_id=7,
            user_shops=["shop-a"],
            max_images=3,
            user_settings=user_settings,
        )

        self.assertEqual(1, len(external_calls))
        self.assertEqual(1, len(internal_calls))
        self.assertEqual(first["candidates"], second["candidates"])


if __name__ == "__main__":
    unittest.main()

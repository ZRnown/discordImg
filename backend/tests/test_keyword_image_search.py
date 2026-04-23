import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from backend.database import Database
from backend.keyword_image_search import KeywordImageSearchError, KeywordImageSearchService


class KeywordImageSearchDatabaseTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.db = Database(str(self.db_path))

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO users (username, password_hash, role)
                VALUES (?, ?, ?)
                """,
                ("tester", "hash", "user"),
            )
            self.user_id = cursor.lastrowid
            cursor.execute(
                """
                INSERT INTO website_configs (
                    name,
                    display_name,
                    url_template,
                    id_pattern
                )
                VALUES (?, ?, ?, ?)
                """,
                ("kakobuy", "Kakobuy", "https://www.kakobuy.com/item/details?url=https://weidian.com/item.html?itemID={id}", "{id}"),
            )
            self.website_id = cursor.lastrowid
            cursor.execute(
                """
                INSERT INTO products (id, product_url, title)
                VALUES (?, ?, ?)
                """,
                (108, "https://weidian.com/item.html?itemID=7653304418", "B30"),
            )
            conn.commit()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_user_website_settings_defaults_include_keyword_image_search_fields(self):
        settings = self.db.get_user_website_settings(self.user_id, self.website_id)

        self.assertEqual(settings["keyword_image_search_enabled"], 0)
        self.assertEqual(settings["keyword_image_search_mode"], "manual")
        self.assertEqual(settings["keyword_image_search_max_images"], 3)

    def test_update_user_website_rotation_persists_keyword_image_search_fields(self):
        ok = self.db.update_user_website_rotation(
            self.user_id,
            self.website_id,
            rotation_interval=180,
            rotation_enabled=1,
            reply_mode="rotation",
            keyword_image_search_enabled=1,
            keyword_image_search_mode="auto",
            keyword_image_search_max_images=5,
        )

        self.assertTrue(ok)
        settings = self.db.get_user_website_settings(self.user_id, self.website_id)
        self.assertEqual(settings["keyword_image_search_enabled"], 1)
        self.assertEqual(settings["keyword_image_search_mode"], "auto")
        self.assertEqual(settings["keyword_image_search_max_images"], 5)

    def test_keyword_image_search_job_crud_round_trip(self):
        candidates = [
            {
                "external_image_url": "https://example.com/image-1.jpg",
                "external_page_url": "https://example.com/page-1",
                "external_title": "Dior B30 product image",
                "match_found": True,
                "similarity": 0.98,
                "send_url": "https://www.kakobuy.com/item/details?url=https://weidian.com/item.html?itemID=7653304418",
                "product": {
                    "id": 108,
                    "title": "B30",
                    "weidianUrl": "https://weidian.com/item.html?itemID=7653304418",
                },
            }
        ]

        job_id = self.db.create_keyword_image_search_job(
            user_id=self.user_id,
            website_id=self.website_id,
            query_text="dior b30",
            channel_id="123",
            message_id="456",
            guild_id="789",
            author_id="999",
            mode="manual",
            provider="google_cse",
            status="ready",
            candidates=candidates,
            external_result_count=3,
            matched_result_count=1,
        )

        self.assertIsInstance(job_id, int)

        stored = self.db.get_keyword_image_search_job(job_id, user_id=self.user_id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored["website_id"], self.website_id)
        self.assertEqual(stored["website_display_name"], "Kakobuy")
        self.assertEqual(stored["status"], "ready")
        self.assertEqual(stored["external_result_count"], 3)
        self.assertEqual(stored["matched_result_count"], 1)
        self.assertEqual(stored["candidates"][0]["product"]["id"], 108)

        listed = self.db.list_keyword_image_search_jobs(self.user_id, limit=10)
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["id"], job_id)

        updated = self.db.update_keyword_image_search_job(
            job_id,
            user_id=self.user_id,
            status="sent",
            selected_candidate_index=0,
            sent_product_id=108,
        )
        self.assertTrue(updated)

        refreshed = self.db.get_keyword_image_search_job(job_id, user_id=self.user_id)
        self.assertEqual(refreshed["status"], "sent")
        self.assertEqual(refreshed["selected_candidate_index"], 0)
        self.assertEqual(refreshed["sent_product_id"], 108)

    def test_user_settings_round_trip_keyword_image_provider_credentials(self):
        ok = self.db.update_user_settings(
            user_id=self.user_id,
            keyword_image_search_api_key="api-key-123",
            keyword_image_search_cx="cx-456",
        )

        self.assertTrue(ok)
        settings = self.db.get_user_settings(self.user_id)
        self.assertEqual(settings["keyword_image_search_api_key"], "api-key-123")
        self.assertEqual(settings["keyword_image_search_cx"], "cx-456")

class KeywordImageSearchServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.service = KeywordImageSearchService()

    @patch("backend.keyword_image_search.config.KEYWORD_IMAGE_SEARCH_PROVIDER", "searchapi_google_images")
    @patch("backend.keyword_image_search.config.SEARCHAPI_IMAGE_SEARCH_API_KEY", "")
    def test_searchapi_google_images_uses_user_key_and_parses_results(self):
        response = Mock()
        response.ok = True
        response.json.return_value = {
            "images": [
                {
                    "title": "Dior B30 Sneakers",
                    "original": {"link": "https://img.example.com/b30.jpg"},
                    "thumbnail": {"link": "https://img.example.com/b30-thumb.jpg"},
                    "source": {
                        "link": "https://example.com/dior-b30",
                        "title": "Example Store",
                    },
                },
                {
                    "title": "Ignored overflow result",
                    "original": {"link": "https://img.example.com/ignored.jpg"},
                },
            ]
        }
        self.service.session.get = Mock(return_value=response)

        results = self.service._search_searchapi_google_images(
            "dior b30",
            1,
            credentials={"api_key": "searchapi-key"},
        )

        self.service.session.get.assert_called_once()
        called_params = self.service.session.get.call_args.kwargs["params"]
        self.assertEqual(called_params["api_key"], "searchapi-key")
        self.assertEqual(called_params["engine"], "google_images")
        self.assertEqual(called_params["q"], "dior b30")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["image_url"], "https://img.example.com/b30.jpg")
        self.assertEqual(results[0]["thumbnail_url"], "https://img.example.com/b30-thumb.jpg")
        self.assertEqual(results[0]["page_url"], "https://example.com/dior-b30")

    @patch("backend.keyword_image_search.config.KEYWORD_IMAGE_SEARCH_PROVIDER", "searchapi_google_images")
    @patch("backend.keyword_image_search.config.SEARCHAPI_IMAGE_SEARCH_API_KEY", "")
    def test_searchapi_google_images_requires_key(self):
        with self.assertRaises(KeywordImageSearchError):
            self.service._search_searchapi_google_images(
                "dior b30",
                3,
                credentials={"api_key": ""},
            )

    @patch("backend.keyword_image_search.config.KEYWORD_IMAGE_SEARCH_PROVIDER", "searchapi_google_images")
    def test_search_candidates_reports_searchapi_provider(self):
        self.service._search_searchapi_google_images = Mock(
            return_value=[
                {
                    "image_url": "https://img.example.com/b30.jpg",
                    "page_url": "https://example.com/dior-b30",
                    "title": "Dior B30 Sneakers",
                    "thumbnail_url": "https://img.example.com/b30-thumb.jpg",
                }
            ]
        )
        self.service._search_internal_by_image = Mock(return_value=None)

        result = self.service.search_candidates(
            query_text="dior b30",
            website_config={"image_similarity_threshold": 0.75},
            max_images=3,
            user_settings={"keyword_image_search_api_key": "searchapi-key"},
        )

        self.assertEqual(result["provider"], "searchapi_google_images")
        self.assertEqual(result["external_result_count"], 1)
        self.assertEqual(result["matched_result_count"], 0)


if __name__ == "__main__":
    unittest.main()

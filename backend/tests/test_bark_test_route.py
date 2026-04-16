import sys
import types
import unittest
from unittest.mock import patch

if "feature_extractor" not in sys.modules:
    feature_extractor_stub = types.ModuleType("feature_extractor")
    feature_extractor_stub.get_feature_extractor = lambda *args, **kwargs: None
    feature_extractor_stub.DINOv2FeatureExtractor = object
    sys.modules["feature_extractor"] = feature_extractor_stub
    sys.modules["backend.feature_extractor"] = feature_extractor_stub

from backend import app as app_module


class _FakeResponse:
    def __init__(self, status_code, text="", json_data=None):
        self.status_code = status_code
        self.text = text
        self._json_data = json_data

    def json(self):
        if self._json_data is None:
            raise ValueError("no json payload")
        return self._json_data


class _FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.trust_env = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self._responses.pop(0)

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self._responses.pop(0)


class BarkTestRouteTestCase(unittest.TestCase):
    def test_bark_test_route_auto_converts_device_token(self):
        session = _FakeSession(
            [
                _FakeResponse(400, text="failed to get device token"),
                _FakeResponse(
                    200,
                    json_data={"data": {"device_key": "converted-device-key"}},
                ),
                _FakeResponse(200, text="ok"),
            ]
        )

        with patch.object(
            app_module,
            "get_current_user",
            return_value={"id": 7, "username": "tester"},
        ), patch.object(
            app_module.db,
            "get_user_settings",
            return_value={
                "bark_server_url": "https://api.day.app",
                "bark_device_key": "",
            },
        ), patch.object(
            app_module.requests,
            "Session",
            return_value=session,
        ):
            client = app_module.app.test_client()
            response = client.post(
                "/api/user/bark-test",
                json={
                    "bark_server_url": "https://api.day.app",
                    "bark_device_key": "a" * 64,
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["device_key_updated"], "converted-device-key")
        self.assertIn("DeviceToken", payload["hint"])
        self.assertEqual([call[0] for call in session.calls], ["GET", "POST", "GET"])
        self.assertEqual(session.calls[1][1], "https://api.day.app/register")
        self.assertTrue(
            session.calls[2][1].startswith("https://api.day.app/converted-device-key/")
        )

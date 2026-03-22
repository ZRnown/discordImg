import unittest
from types import SimpleNamespace

from backend.message_filter_utils import (
    filters_block_message,
    get_keyword_match_limit_from_filters,
    resolve_keyword_match_limit,
)


class MessageFilterHelperTestCase(unittest.TestCase):
    def _make_message(self, role_ids=None):
        author_roles = [SimpleNamespace(id=role_id) for role_id in (role_ids or [])]
        author = SimpleNamespace(id=123456789, name="tester", roles=author_roles)
        return SimpleNamespace(
            content="hello world",
            author=author,
            guild=SimpleNamespace(id=987654321),
        )

    def test_role_id_filter_supports_multiple_values(self):
        client = SimpleNamespace(_message_has_image=lambda message: False)
        message = self._make_message(role_ids=[222])

        blocked = filters_block_message(
            message,
            [
                {
                    "filter_type": "role_id",
                    "filter_value": "111， 222\n333",
                }
            ],
            message_has_image=client._message_has_image,
        )

        self.assertTrue(blocked)

    def test_keyword_match_limit_prefers_smallest_positive_filter(self):
        limit = get_keyword_match_limit_from_filters(
            [
                {"filter_type": "keyword_match_limit", "filter_value": "5"},
                {"filter_type": "keyword_match_limit", "filter_value": "2"},
                {"filter_type": "keyword_match_limit", "filter_value": "0"},
            ]
        )

        self.assertEqual(limit, 2)

    def test_keyword_match_limit_returns_zero_for_explicit_unlimited_rule(self):
        limit = get_keyword_match_limit_from_filters(
            [
                {"filter_type": "contains", "filter_value": "http"},
                {"filter_type": "keyword_match_limit", "filter_value": "0"},
            ]
        )

        self.assertEqual(limit, 0)

    def test_keyword_match_limit_rule_overrides_legacy_setting(self):
        limit = resolve_keyword_match_limit(
            [
                {"filter_type": "keyword_match_limit", "filter_value": "2"},
            ],
            fallback_limit=5,
        )

        self.assertEqual(limit, 2)


if __name__ == "__main__":
    unittest.main()

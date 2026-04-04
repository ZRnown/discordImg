import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.bot import DiscordBotClient
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


class ManagedAccountMessageGuardTestCase(unittest.IsolatedAsyncioTestCase):
    def _build_client(self):
        return SimpleNamespace(
            running=True,
            user=SimpleNamespace(id=999999),
            user_id=42,
            role='both',
            _should_ignore_mass_or_activity_message=lambda message: False,
            _notify_direct_interaction_if_needed=AsyncMock(),
            _is_account_bound_in_channel=AsyncMock(return_value=(True, None)),
        )

    def _build_message(self, author_id):
        return SimpleNamespace(
            author=SimpleNamespace(id=author_id, bot=False),
            webhook_id=None,
            guild=SimpleNamespace(id=1),
            mentions=[],
            reference=None,
            id=123456789,
            channel=SimpleNamespace(id=987654321, name='finds'),
            content='https://www.kakobuy.com/item/details?url=test',
        )

    async def test_managed_account_message_exits_before_reply_pipeline(self):
        client = self._build_client()
        message = self._build_message(author_id=111)
        managed_sender = SimpleNamespace(user=SimpleNamespace(id=111))

        with patch('backend.bot.bot_clients', [managed_sender]), patch(
            'backend.bot.mark_message_as_processed',
            side_effect=AssertionError('managed account message should not enter dedupe'),
        ):
            await DiscordBotClient.on_message(client, message)

        client._notify_direct_interaction_if_needed.assert_not_awaited()
        client._is_account_bound_in_channel.assert_not_awaited()

    async def test_regular_user_message_still_reaches_dedupe(self):
        client = self._build_client()
        message = self._build_message(author_id=222)
        managed_sender = SimpleNamespace(user=SimpleNamespace(id=111))

        with patch('backend.bot.bot_clients', [managed_sender]), patch(
            'backend.bot.mark_message_as_processed',
            return_value=False,
        ) as mark_processed:
            await DiscordBotClient.on_message(client, message)

        client._notify_direct_interaction_if_needed.assert_awaited_once()
        client._is_account_bound_in_channel.assert_awaited_once_with(message.channel.id)
        mark_processed.assert_called_once_with(message.id, client.user_id)


if __name__ == "__main__":
    unittest.main()

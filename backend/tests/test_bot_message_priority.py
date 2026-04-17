import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.bot import DiscordBotClient


class BotMessagePriorityTestCase(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    async def _await_stage(_message, _stage, coro, _timeout):
        return await coro

    def _build_client(self):
        return SimpleNamespace(
            running=True,
            user=SimpleNamespace(id=999999, name="listener"),
            user_id=42,
            account_id=3,
            role="both",
            _should_process_self_authored_message=lambda message: False,
            _should_allow_managed_account_trigger=lambda message: True,
            _is_plain_text_keyword_trigger_candidate=lambda message: True,
            _log_message_skip=lambda message, reason: None,
            _message_preview=lambda message, limit=120: getattr(message, "content", ""),
            _should_ignore_mass_or_activity_message=lambda message: False,
            _notify_direct_interaction_if_needed=AsyncMock(),
            _is_account_bound_in_channel=AsyncMock(return_value=(True, None)),
            get_website_configs_by_channel_async=AsyncMock(return_value=[{
                "id": 11,
                "display_name": "Test Site",
                "reply_language": ["en"],
            }]),
            _exclude_blocked_website_configs=AsyncMock(side_effect=lambda _message, website_configs: website_configs),
            _get_user_website_settings_map_for_configs=AsyncMock(return_value={}),
            _apply_website_block_user_triggers=AsyncMock(return_value=set()),
            _should_filter_message=lambda message: False,
            handle_keyword_forward=AsyncMock(),
            handle_keyword_search=AsyncMock(return_value=False),
            handle_image=AsyncMock(),
            _run_message_stage_with_timeout=AsyncMock(side_effect=self._await_stage),
            _get_user_settings_safe=AsyncMock(return_value={
                "keyword_reply_enabled": 1,
                "image_reply_enabled": 1,
            }),
        )

    def _build_message(self):
        attachment = SimpleNamespace(
            filename="shoe.jpg",
            content_type="image/jpeg",
        )
        return SimpleNamespace(
            author=SimpleNamespace(id=222, name="buyer", bot=False),
            webhook_id=None,
            guild=SimpleNamespace(id=1),
            mentions=[],
            reference=None,
            id=123456789,
            channel=SimpleNamespace(id=987654321, name="finds"),
            content="aj4 black cat",
            attachments=[attachment],
        )

    async def test_text_hit_skips_image_processing(self):
        client = self._build_client()
        message = self._build_message()
        client.handle_keyword_search = AsyncMock(return_value=True)
        website_configs = client.get_website_configs_by_channel_async.return_value

        with patch("backend.bot.bot_clients", []), patch(
            "backend.bot.mark_message_as_processed",
            return_value=True,
        ):
            await DiscordBotClient.on_message(client, message)

        client.handle_keyword_search.assert_awaited_once_with(
            message,
            website_configs_override=website_configs,
            allow_keyword_image_search=False,
        )
        client.handle_image.assert_not_awaited()

    async def test_image_processing_runs_when_text_does_not_hit(self):
        client = self._build_client()
        message = self._build_message()
        website_configs = client.get_website_configs_by_channel_async.return_value

        with patch("backend.bot.bot_clients", []), patch(
            "backend.bot.mark_message_as_processed",
            return_value=True,
        ):
            await DiscordBotClient.on_message(client, message)

        client.handle_keyword_search.assert_awaited_once_with(
            message,
            website_configs_override=website_configs,
            allow_keyword_image_search=False,
        )
        client.handle_image.assert_awaited_once_with(
            message,
            message.attachments[0],
            website_configs_override=website_configs,
        )

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend.bot import DiscordBotClient


def _build_message(content: str):
    return SimpleNamespace(
        content=content,
        guild=SimpleNamespace(id=1),
        attachments=[],
        reference=None,
        mentions=[],
        author=SimpleNamespace(id=42, name="buyer"),
        channel=SimpleNamespace(id=99, name="finds"),
    )


class BotKeywordLoggingTestCase(unittest.TestCase):
    def test_keyword_candidate_skip_logs_at_info_level(self):
        client = SimpleNamespace(
            user=SimpleNamespace(name="listener"),
            account_id=3,
            _message_preview=lambda message, limit=120: message.content,
            _is_plain_text_keyword_trigger_candidate=lambda message: True,
        )
        message = _build_message("aj4 black cat")

        with patch("backend.bot.logger.info") as mock_info, patch(
            "backend.bot.logger.debug"
        ) as mock_debug:
            DiscordBotClient._log_message_skip(client, message, "当前账号未绑定该频道")

        mock_info.assert_called_once()
        mock_debug.assert_not_called()

    def test_non_keyword_skip_stays_at_debug_level(self):
        client = SimpleNamespace(
            user=SimpleNamespace(name="listener"),
            account_id=3,
            _message_preview=lambda message, limit=120: "[附件]",
            _is_plain_text_keyword_trigger_candidate=lambda message: False,
        )
        message = _build_message("")
        message.attachments = [SimpleNamespace(filename="photo.jpg", content_type="image/jpeg")]

        with patch("backend.bot.logger.info") as mock_info, patch(
            "backend.bot.logger.debug"
        ) as mock_debug:
            DiscordBotClient._log_message_skip(client, message, "消息包含@提及")

        mock_info.assert_not_called()
        mock_debug.assert_called_once()

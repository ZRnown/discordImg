from unittest.mock import patch

from backend import bot as bot_module
from backend.bot import (
    MESSAGE_IMAGE_REPLY_TIMEOUT_SECONDS,
    _get_image_recognition_request_timeout_seconds,
)


def test_image_recognition_request_timeout_tracks_stage_timeout():
    assert _get_image_recognition_request_timeout_seconds(
        MESSAGE_IMAGE_REPLY_TIMEOUT_SECONDS
    ) == 85.0


def test_image_recognition_request_timeout_never_drops_below_floor():
    assert _get_image_recognition_request_timeout_seconds(20) == 30.0


def test_build_discord_client_runtime_options_disable_startup_chunking_by_default():
    options = bot_module.build_discord_client_runtime_options()

    assert options["chunk_guilds_at_startup"] is False
    assert options["guild_subscriptions"] is False
    assert options["heartbeat_timeout"] == 120.0
    assert options["max_messages"] == 200
    if hasattr(bot_module.discord, "MemberCacheFlags"):
        assert options["member_cache_flags"] == bot_module.discord.MemberCacheFlags.none()


def test_get_discord_start_delay_seconds_uses_configured_stagger():
    with patch.object(bot_module.config, "DISCORD_STARTUP_STAGGER_SECONDS", 1.75, create=True):
        assert bot_module.get_discord_start_delay_seconds(0) == 0.0
        assert bot_module.get_discord_start_delay_seconds(1) == 1.75
        assert bot_module.get_discord_start_delay_seconds(3) == 5.25

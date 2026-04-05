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

from backend.image_query_text import build_image_query_text


class _Message:
    def __init__(self, clean_content=None, content=None):
        self.clean_content = clean_content
        self.content = content


def test_build_image_query_text_prefers_clean_content_and_normalizes_whitespace():
    message = _Message(clean_content="  Brazil   x\nCorteiz  tracksuit  ", content="ignored")

    assert build_image_query_text(message) == "Brazil x Corteiz tracksuit"


def test_build_image_query_text_returns_empty_for_attachment_only_message():
    message = _Message(clean_content=None, content=" \n ")

    assert build_image_query_text(message) == ""

from pathlib import Path

from backend.database import Database


def _create_website(db: Database, name: str) -> int:
    ok, error = db.add_website_config(
        name=name,
        display_name=name,
        url_template=f"https://{name}.example/{{id}}",
        id_pattern=r"\\d+",
    )
    assert ok, error
    for config in db.get_website_configs():
        if config["name"] == name:
            return config["id"]
    raise AssertionError(f"website {name} not found")


def test_channel_lookup_falls_back_to_parent_channel_when_thread_has_no_binding(tmp_path: Path):
    db = Database(db_path=str(tmp_path / "metadata.db"))
    website_id = _create_website(db, "acbuy")
    assert db.add_website_channel_binding(website_id, "parent-channel", user_id=7)

    configs = db.get_website_configs_by_channel(["thread-channel", "parent-channel"], user_id=7)

    assert [config["name"] for config in configs] == ["acbuy"]


def test_channel_lookup_prefers_thread_binding_over_parent_channel(tmp_path: Path):
    db = Database(db_path=str(tmp_path / "metadata.db"))
    parent_website_id = _create_website(db, "acbuy")
    thread_website_id = _create_website(db, "oopbuy")
    assert db.add_website_channel_binding(parent_website_id, "parent-channel", user_id=7)
    assert db.add_website_channel_binding(thread_website_id, "thread-channel", user_id=7)

    configs = db.get_website_configs_by_channel(["thread-channel", "parent-channel"], user_id=7)

    assert [config["name"] for config in configs] == ["oopbuy"]

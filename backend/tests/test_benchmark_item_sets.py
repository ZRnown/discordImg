import json

from backend.benchmarks.item_sets import flatten_item_queries, load_item_set


def test_load_item_set_supports_query_groups(tmp_path):
    items_file = tmp_path / "tip-v2.json"
    items_file.write_text(
        json.dumps(
            {
                "dataset_name": "tip-v2",
                "items": [
                    {
                        "item_id": "7683240673",
                        "title": "DR卡夹",
                        "query_groups": {
                            "clean_web": ["Dior cardholder"],
                            "discord_noise": ["thumb DR卡夹"],
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    dataset_name, items = load_item_set(items_file)

    assert dataset_name == "tip-v2"
    assert items == [
        {
            "item_id": "7683240673",
            "title": "DR卡夹",
            "queries": ["Dior cardholder", "thumb DR卡夹"],
            "query_groups": {
                "clean_web": ["Dior cardholder"],
                "discord_noise": ["thumb DR卡夹"],
            },
        }
    ]


def test_flatten_item_queries_filters_selected_groups():
    item = {
        "item_id": "7686244082",
        "title": "EM-巴西夹风衣",
        "query_groups": {
            "clean_web": ["Brazil x Corteiz tracksuit"],
            "discord_noise": ["thumb EM-巴西夹风衣"],
        },
    }

    queries = flatten_item_queries(item, selected_groups=["discord_noise"])

    assert queries == [
        {
            "text": "thumb EM-巴西夹风衣",
            "group": "discord_noise",
        }
    ]

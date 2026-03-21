from pathlib import Path

from backend.benchmarks import fetch_dataset


class FakeScraper:
    def scrape_product_info(self, item_url):
        return {
            "title": "Demo",
            "shop_name": "TIP",
            "images": [
                "https://example.com/catalog-1.jpg",
                "https://example.com/catalog-2.jpg",
            ],
        }


def test_build_item_record_keeps_query_limit_per_group(tmp_path, monkeypatch):
    catalog_dir = tmp_path / "catalog"
    query_dir = tmp_path / "queries"
    monkeypatch.setattr(fetch_dataset, "CATALOG_DIR", catalog_dir)
    monkeypatch.setattr(fetch_dataset, "QUERY_DIR", query_dir)

    def fake_fetch(_session, query, limit=12):
        return [
            f"https://example.com/{query}-1.jpg",
            f"https://example.com/{query}-2.jpg",
            f"https://example.com/{query}-3.jpg",
        ]

    def fake_download(_session, url, out_path):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(url.encode("utf-8"))
        return out_path

    monkeypatch.setattr(fetch_dataset, "fetch_bing_search_image_urls", fake_fetch)
    monkeypatch.setattr(fetch_dataset, "download_image", fake_download)

    item = {
        "item_id": "7683240673",
        "title": "DR卡夹",
        "queries": ["Dior cardholder", "thumb DR卡夹"],
        "query_groups": {
            "clean_web": ["Dior cardholder"],
            "discord_noise": ["thumb DR卡夹"],
        },
    }

    record = fetch_dataset.build_item_record(
        item,
        scraper=FakeScraper(),
        session=object(),
        product_image_limit=2,
        query_image_limit=2,
        selected_query_groups=["clean_web", "discord_noise"],
    )

    assert len(record["product_images"]) == 2
    assert len(record["query_images"]) == 4
    assert [image["query_group"] for image in record["query_images"]] == [
        "clean_web",
        "clean_web",
        "discord_noise",
        "discord_noise",
    ]

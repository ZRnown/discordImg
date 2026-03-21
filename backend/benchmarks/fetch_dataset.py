from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Dict, Iterable, List, Optional
from urllib.parse import quote

import requests
from PIL import Image, UnidentifiedImageError

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
CATALOG_DIR = DATA_DIR / "catalog"
QUERY_DIR = DATA_DIR / "queries"
MANIFEST_PATH = DATA_DIR / "manifest.json"


def _backend_path() -> Path:
    return ROOT.parent


if str(_backend_path()) not in sys.path:
    sys.path.insert(0, str(_backend_path()))

from benchmarks.common import parse_bing_image_urls  # noqa: E402
from benchmarks.item_sets import flatten_item_queries, load_item_set  # noqa: E402
from weidian_scraper import WeidianScraper  # noqa: E402


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CATALOG_DIR.mkdir(parents=True, exist_ok=True)
    QUERY_DIR.mkdir(parents=True, exist_ok=True)


def sha1_url(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]


def verify_image(path: Path) -> bool:
    try:
        with Image.open(path) as img:
            img.verify()
        return path.stat().st_size > 256
    except (UnidentifiedImageError, OSError):
        return False


def download_image(session: requests.Session, url: str, out_path: Path) -> Optional[Path]:
    if out_path.exists() and verify_image(out_path):
        return out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        response = session.get(
            url,
            timeout=(10, 20),
            headers={"User-Agent": "Mozilla/5.0"},
            stream=True,
        )
        response.raise_for_status()
        with out_path.open("wb") as fh:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    fh.write(chunk)
    except Exception:
        if out_path.exists():
            out_path.unlink()
        return None

    if not verify_image(out_path):
        out_path.unlink(missing_ok=True)
        return None
    return out_path


def fetch_bing_search_image_urls(session: requests.Session, query: str, limit: int = 12) -> List[str]:
    url = "https://www.bing.com/images/search?q=" + quote(query)
    response = session.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=(10, 20))
    response.raise_for_status()
    return parse_bing_image_urls(response.text, limit=limit)


def build_item_record(
    item: Dict,
    scraper: WeidianScraper,
    session: requests.Session,
    product_image_limit: int,
    query_image_limit: int,
    selected_query_groups: Optional[Iterable[str]],
) -> Dict:
    item_id = item["item_id"]
    item_url = f"https://weidian.com/item.html?itemID={item_id}"
    info = scraper.scrape_product_info(item_url)
    if not info:
        raise RuntimeError(f"failed to fetch product info for {item_id}")

    product_dir = CATALOG_DIR / item_id
    query_dir = QUERY_DIR / item_id
    product_dir.mkdir(parents=True, exist_ok=True)
    query_dir.mkdir(parents=True, exist_ok=True)

    product_images = []
    for index, image_url in enumerate((info.get("images") or [])[:product_image_limit], start=1):
        suffix = Path(image_url.split("?")[0]).suffix or ".jpg"
        out_path = product_dir / f"{index:02d}{suffix}"
        saved = download_image(session, image_url, out_path)
        if saved:
            product_images.append(
                {
                    "source_url": image_url,
                    "local_path": str(saved),
                    "image_index": index - 1,
                }
            )

    query_images = []
    seen_query_urls = set()
    for query_spec in flatten_item_queries(item, selected_query_groups):
        query = query_spec["text"]
        query_group = query_spec["group"]
        group_image_count = 0
        for image_url in fetch_bing_search_image_urls(session, query):
            if image_url in seen_query_urls:
                continue
            seen_query_urls.add(image_url)
            suffix = Path(image_url.split("?")[0]).suffix or ".jpg"
            out_path = query_dir / f"{sha1_url(image_url)}{suffix}"
            saved = download_image(session, image_url, out_path)
            if not saved:
                continue
            query_images.append(
                {
                    "query": query,
                    "query_group": query_group,
                    "source_url": image_url,
                    "local_path": str(saved),
                }
            )
            group_image_count += 1
            if group_image_count >= query_image_limit:
                break

    return {
        "item_id": item_id,
        "title": info.get("title") or item.get("title") or "",
        "shop_name": info.get("shop_name") or "",
        "product_url": item_url,
        "queries": list(item.get("queries", [])),
        "query_groups": dict(item.get("query_groups", {})),
        "product_images": product_images,
        "query_images": query_images,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build retrieval benchmark dataset.")
    parser.add_argument("--items-file", default="")
    parser.add_argument("--limit-items", type=int, default=0, help="Only build the first N benchmark items.")
    parser.add_argument("--product-image-limit", type=int, default=8)
    parser.add_argument("--query-image-limit", type=int, default=4)
    parser.add_argument("--query-groups", default="", help="Comma-separated query groups to include.")
    parser.add_argument("--dataset-name", default="")
    parser.add_argument("--manifest-path", default=str(MANIFEST_PATH))
    args = parser.parse_args()

    ensure_dirs()
    scraper = WeidianScraper()
    session = requests.Session()
    session.trust_env = False

    selected_query_groups = [group.strip() for group in args.query_groups.split(",") if group.strip()]
    loaded_dataset_name, loaded_items = load_item_set(args.items_file or None)
    items = loaded_items[: args.limit_items] if args.limit_items else loaded_items
    dataset_name = args.dataset_name.strip() or loaded_dataset_name
    manifest_path = Path(args.manifest_path)
    manifest = {
        "meta": {
            "dataset_name": dataset_name,
            "items_file": args.items_file or "benchmarks.items",
            "query_groups": selected_query_groups,
        },
        "items": [],
    }
    failures = []

    for item in items:
        try:
            record = build_item_record(
                item,
                scraper=scraper,
                session=session,
                product_image_limit=args.product_image_limit,
                query_image_limit=args.query_image_limit,
                selected_query_groups=selected_query_groups or None,
            )
            manifest["items"].append(record)
            print(
                f"[ok] {item['item_id']} {record['title']} "
                f"catalog={len(record['product_images'])} query={len(record['query_images'])}"
            )
        except Exception as exc:
            failures.append({"item_id": item["item_id"], "error": str(exc)})
            print(f"[fail] {item['item_id']} {exc}")

    manifest["failures"] = failures
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"manifest -> {manifest_path}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())

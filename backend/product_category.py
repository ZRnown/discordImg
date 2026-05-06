from __future__ import annotations

import re
from typing import Any


_CATEGORY_KEYWORDS = {
    "shoe": (
        "shoe",
        "shoes",
        "sneaker",
        "sneakers",
        "trainer",
        "trainers",
        "runner",
        "running",
        "boot",
        "boots",
        "sandal",
        "sandals",
        "slipper",
        "slippers",
        "dunk",
        "jordan",
        "yeezy",
        "鞋",
        "球鞋",
        "运动鞋",
        "跑鞋",
        "板鞋",
        "拖鞋",
        "凉鞋",
        "靴",
    ),
    "pants": (
        "pants",
        "trousers",
        "jeans",
        "shorts",
        "joggers",
        "sweatpants",
        "cargo",
        "裤",
        "短裤",
        "长裤",
        "牛仔裤",
        "运动裤",
        "工装裤",
    ),
    "watch": (
        "watch",
        "watches",
        "rolex",
        "omega",
        "手表",
        "腕表",
        "表",
    ),
    "bag": (
        "bag",
        "bags",
        "backpack",
        "handbag",
        "purse",
        "wallet",
        "tote",
        "duffle",
        "crossbody",
        "包",
        "背包",
        "单肩包",
        "斜挎包",
        "手提包",
        "钱包",
        "腰包",
        "挎包",
    ),
    "top": (
        "shirt",
        "tshirt",
        "tee",
        "hoodie",
        "sweater",
        "sweatshirt",
        "jacket",
        "coat",
        "jersey",
        "vest",
        "polo",
        "卫衣",
        "短袖",
        "长袖",
        "上衣",
        "外套",
        "夹克",
        "衬衫",
        "毛衣",
        "球衣",
        "训练服",
        "套装",
        "T恤",
    ),
}


def _normalize_text(*values: Any) -> str:
    return " ".join(str(value or "").strip().lower() for value in values if str(value or "").strip())


def infer_product_category(*values: Any) -> str:
    text = _normalize_text(*values)
    if not text:
        return ""

    ascii_tokens = set(re.findall(r"[a-z0-9]+", text))
    best_category = ""
    best_score = 0
    for category, keywords in _CATEGORY_KEYWORDS.items():
        score = 0
        for keyword in keywords:
            normalized_keyword = keyword.lower()
            if re.fullmatch(r"[a-z0-9]+", normalized_keyword):
                if normalized_keyword in ascii_tokens:
                    score += 2
            elif normalized_keyword in text:
                score += 2 if len(normalized_keyword) >= 2 else 1
        if score > best_score:
            best_category = category
            best_score = score

    return best_category if best_score > 0 else ""

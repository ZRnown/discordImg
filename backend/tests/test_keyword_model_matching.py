import unittest

from backend.keyword_search_terms import (
    build_product_keyword_variants,
    build_query_keyword_candidates,
)


class KeywordModelMatchingTestCase(unittest.TestCase):
    def test_b30_query_does_not_match_plain_30_variant(self):
        query_keywords = set(build_query_keyword_candidates("b 30").keys())
        plain_30_product = build_product_keyword_variants("Asics Gel Kayano 30")
        b30_product = build_product_keyword_variants("Dior B30, B30, B 30, Dior b30s")

        self.assertFalse(query_keywords.intersection(plain_30_product))
        self.assertIn("b30", query_keywords.intersection(b30_product))


if __name__ == "__main__":
    unittest.main()

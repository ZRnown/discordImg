import unittest

from backend.keyword_search_terms import (
    build_product_keyword_variants,
    build_query_keyword_candidates,
    find_query_keyword_match,
)


class KeywordModelMatchingTestCase(unittest.TestCase):
    def test_b30_query_does_not_match_plain_30_variant(self):
        query_keywords = set(build_query_keyword_candidates("b 30").keys())
        plain_30_product = build_product_keyword_variants("Asics Gel Kayano 30")
        b30_product = build_product_keyword_variants("Dior B30, B30, B 30, Dior b30s")

        self.assertFalse(query_keywords.intersection(plain_30_product))
        self.assertIn("b30", query_keywords.intersection(b30_product))

    def test_split_numeric_expression_does_not_match_plain_11_variant(self):
        query_keywords = set(build_query_keyword_candidates("1+1").keys())
        jersey_product = build_product_keyword_variants("Jersey 11")

        self.assertFalse(query_keywords.intersection(jersey_product))

    def test_single_word_does_not_match_multi_word_phrase(self):
        reason = find_query_keyword_match(
            build_query_keyword_candidates("hoodie"),
            "Palace hoodie",
        )

        self.assertIsNone(reason)

    def test_exact_match_helper_rejects_substring_only_match(self):
        reason = find_query_keyword_match(
            build_query_keyword_candidates("jack"),
            "Down Jacket, Winter Coat",
        )

        self.assertIsNone(reason)

    def test_exact_match_helper_falls_back_to_title_when_english_keywords_missing(self):
        reason = find_query_keyword_match(
            build_query_keyword_candidates("b 30"),
            "",
            "Dior B30",
        )

        self.assertIsNotNone(reason)
        self.assertEqual(reason["canonical_keyword"], "b30")
        self.assertEqual(reason["source"], "title")

    def test_multi_word_phrase_matches_same_phrase(self):
        reason = find_query_keyword_match(
            build_query_keyword_candidates("Palace Hoodie"),
            "Palace hoodie",
        )

        self.assertIsNotNone(reason)
        self.assertEqual(reason["canonical_keyword"], "palacehoodie")
        self.assertEqual(reason["source"], "english_title")

    def test_compact_phrase_matches_spaced_phrase(self):
        reason = find_query_keyword_match(
            build_query_keyword_candidates("Palacehoodie"),
            "Palace hoodie",
        )

        self.assertIsNotNone(reason)
        self.assertEqual(reason["canonical_keyword"], "palacehoodie")
        self.assertEqual(reason["source"], "english_title")


if __name__ == "__main__":
    unittest.main()

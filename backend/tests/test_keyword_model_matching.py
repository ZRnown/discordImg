import unittest

from backend.keyword_search_terms import (
    build_product_keyword_variants,
    build_query_keyword_candidates,
    find_query_keyword_match,
    normalize_partition_match_rules,
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

    def test_multi_word_phrase_does_not_match_other_phrase_via_shared_single_word(self):
        reason = find_query_keyword_match(
            build_query_keyword_candidates("Pony sweatpants"),
            "Pony jacket, Pony jacket black",
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

    def test_longer_query_can_match_shorter_core_phrase(self):
        reason = find_query_keyword_match(
            build_query_keyword_candidates("Lv skate swarovski"),
            "LV Skate",
        )

        self.assertIsNotNone(reason)
        self.assertEqual(reason["canonical_keyword"], "lvskate")
        self.assertEqual(reason["source"], "english_title")

    def test_longer_query_with_suffix_can_match_shorter_phrase(self):
        reason = find_query_keyword_match(
            build_query_keyword_candidates("Palace Hoodie Zip"),
            "Palace hoodie",
        )

        self.assertIsNotNone(reason)
        self.assertEqual(reason["canonical_keyword"], "palacehoodie")
        self.assertEqual(reason["source"], "english_title")

    def test_partition_rules_can_match_split_model_tokens_out_of_order(self):
        query = "I need $30 Dior B30"
        reason = find_query_keyword_match(
            build_query_keyword_candidates(query),
            "",
            "",
            query_text=query,
            partition_match_enabled=True,
            partition_match_rules=[["B", "30"]],
        )

        self.assertIsNotNone(reason)
        self.assertEqual(reason["rule"], "partition_keyword_match")
        self.assertEqual(reason["source"], "partition_row:0")

    def test_partition_rules_can_match_loose_phrase_tokens(self):
        query = "A hoodie like Sp5der's"
        reason = find_query_keyword_match(
            build_query_keyword_candidates(query),
            "",
            "",
            query_text=query,
            partition_match_enabled=True,
            partition_match_rules=[["SP hood"]],
        )

        self.assertIsNotNone(reason)
        self.assertEqual(reason["rule"], "partition_keyword_match")
        self.assertEqual(reason["source"], "partition_row:0")

    def test_partition_mode_disables_english_keyword_fallback(self):
        query = "Palace hoodie"
        reason = find_query_keyword_match(
            build_query_keyword_candidates(query),
            "Palace hoodie",
            "",
            query_text=query,
            partition_match_enabled=True,
            partition_match_rules=[["B", "30"]],
        )

        self.assertIsNone(reason)

    def test_partition_rules_ignore_empty_cells_within_a_row(self):
        query = "I need Dior B30"
        reason = find_query_keyword_match(
            build_query_keyword_candidates(query),
            "",
            "",
            query_text=query,
            partition_match_enabled=True,
            partition_match_rules=[["B", "", "30"]],
        )

        self.assertIsNotNone(reason)
        self.assertEqual(reason["source"], "partition_row:0")

    def test_partition_rules_allow_multiple_rows_as_or_conditions(self):
        query = "Can you find an SP hoodie"
        reason = find_query_keyword_match(
            build_query_keyword_candidates(query),
            "",
            "",
            query_text=query,
            partition_match_enabled=True,
            partition_match_rules=[["B", "30"], ["SP", "", "hood"]],
        )

        self.assertIsNotNone(reason)
        self.assertEqual(reason["source"], "partition_row:1")

    def test_partition_rules_do_not_match_by_query_prefix_only(self):
        query = "best seller for men's bag"

        for rule in (
            [["Supreme Socks"]],
            [["stone shirt"]],
            [["stussy shirt"]],
            [["sp5der shirt"]],
        ):
            with self.subTest(rule=rule):
                reason = find_query_keyword_match(
                    build_query_keyword_candidates(query),
                    "",
                    "",
                    query_text=query,
                    partition_match_enabled=True,
                    partition_match_rules=rule,
                )

                self.assertIsNone(reason)

    def test_partition_rules_keep_prefix_model_matching_from_rule_to_query(self):
        query = "A hoodie like Sp5der's"
        reason = find_query_keyword_match(
            build_query_keyword_candidates(query),
            "",
            "",
            query_text=query,
            partition_match_enabled=True,
            partition_match_rules=[["SP hood"]],
        )

        self.assertIsNotNone(reason)
        self.assertEqual(reason["source"], "partition_row:0")

    def test_partition_rule_normalizer_keeps_matrix_shape_and_drops_empty_rows(self):
        self.assertEqual(
            normalize_partition_match_rules([
                [" B ", " 30 "],
                ["SP hood", "", None],
                ["", ""],
            ]),
            [
                ["B", "30"],
                ["SP hood", "", ""],
            ],
        )


if __name__ == "__main__":
    unittest.main()

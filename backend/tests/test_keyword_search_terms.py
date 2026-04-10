import unittest

from backend.keyword_search_terms import (
    build_query_keyword_candidates,
    build_text_search_plan,
    extract_marketplace_item_id_from_text,
)


class KeywordSearchTermsTestCase(unittest.TestCase):
    def test_extract_marketplace_item_id_from_encoded_kakobuy_url(self):
        query = (
            "https://www.kakobuy.com/item/details?"
            "url=https%3A%2F%2Fweidian.com%2Fitem.html%3FitemID%3D7704997828%26spider_token%3D09e3"
        )

        self.assertEqual(extract_marketplace_item_id_from_text(query), "7704997828")

    def test_extract_marketplace_item_id_from_oopbuy_path_url(self):
        query = "https://oopbuy.com/product/weidian/7653365800"

        self.assertEqual(extract_marketplace_item_id_from_text(query), "7653365800")

    def test_extract_marketplace_item_id_from_bbdbuy_path_url(self):
        query = "https://www.bbdbuyeu.com/goods/WEIDIAN/7467867059"

        self.assertEqual(extract_marketplace_item_id_from_text(query), "7467867059")

    def test_extract_marketplace_item_id_from_acbuy2_direct_id_url(self):
        query = "https://www.acbuy.com/product?id=7460328518&source=WD&u=XNX5L3"

        self.assertEqual(extract_marketplace_item_id_from_text(query), "7460328518")

    def test_extract_marketplace_item_id_returns_none_for_non_product_text(self):
        self.assertIsNone(extract_marketplace_item_id_from_text("nba socks"))

    def test_alpha_numeric_query_does_not_promote_standalone_number_candidate(self):
        candidates = build_query_keyword_candidates("b 30")

        self.assertIn("b30", candidates)
        self.assertNotIn("30", candidates)

    def test_numeric_only_query_keeps_numeric_candidate(self):
        candidates = build_query_keyword_candidates("530")

        self.assertEqual(candidates, {"530": "530"})

    def test_multi_word_phrase_does_not_expand_into_single_word_candidates(self):
        candidates = build_query_keyword_candidates("Pony sweatpants")

        self.assertIn("ponysweatpants", candidates)
        self.assertNotIn("pony", candidates)
        self.assertNotIn("sweatpants", candidates)

    def test_four_word_phrase_keeps_full_phrase_candidate(self):
        candidates = build_query_keyword_candidates("Shark-Fish Sweatpants Collection")

        self.assertIn("sharkfishsweatpantscollection", candidates)

    def test_alpha_numeric_query_does_not_expand_standalone_numeric_search_term(self):
        plan = build_text_search_plan("b 30")

        self.assertEqual(plan["query_normalized"], "b 30")
        self.assertNotIn("30", plan["extra_terms"])
        self.assertNotIn("30", plan["fallback_tokens"])

    def test_numeric_only_query_can_expand_numeric_search_term(self):
        plan = build_text_search_plan("530")

        self.assertIn("530", plan["fallback_tokens"])

    def test_multi_word_phrase_search_plan_does_not_fallback_to_single_words(self):
        plan = build_text_search_plan("Pony sweatpants")

        self.assertEqual(plan["query_normalized"], "pony sweatpants")
        self.assertEqual(plan["fallback_tokens"], [])
        self.assertEqual(plan["extra_terms"], ["pony sweatpants"])

    def test_long_sentence_keeps_standalone_model_candidate(self):
        candidates = build_query_keyword_candidates("啊实打实大路上，的、 b30 啊稍等哈雕塑发给")

        self.assertIn("b30", candidates)

    def test_long_sentence_search_plan_extracts_standalone_model_term(self):
        plan = build_text_search_plan("啊实打实大路上，的、 b30 啊稍等哈雕塑发给")

        self.assertIn("b30", plan["extra_terms"])

    def test_long_sentence_search_plan_extracts_aj1_model_term(self):
        plan = build_text_search_plan("anyone got aj1 low in black")

        self.assertIn("aj1", plan["extra_terms"])

    def test_split_numeric_expression_does_not_collapse_into_model_candidate(self):
        self.assertEqual(build_query_keyword_candidates("1+1"), {})
        self.assertEqual(build_query_keyword_candidates("1 1"), {})

    def test_split_numeric_expression_does_not_leave_fallback_numeric_tokens(self):
        plan = build_text_search_plan("1+1")

        self.assertEqual(plan["query_normalized"], "1 1")
        self.assertEqual(plan["numeric_terms"], [])
        self.assertEqual(plan["extra_terms"], [])
        self.assertEqual(plan["fallback_tokens"], [])


if __name__ == "__main__":
    unittest.main()

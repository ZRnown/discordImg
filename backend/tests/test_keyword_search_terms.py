import unittest

from backend.keyword_search_terms import (
    build_query_keyword_candidates,
    build_text_search_plan,
)


class KeywordSearchTermsTestCase(unittest.TestCase):
    def test_alpha_numeric_query_does_not_promote_standalone_number_candidate(self):
        candidates = build_query_keyword_candidates("b 30")

        self.assertIn("b30", candidates)
        self.assertNotIn("30", candidates)

    def test_numeric_only_query_keeps_numeric_candidate(self):
        candidates = build_query_keyword_candidates("530")

        self.assertEqual(candidates, {"530": "530"})

    def test_alpha_numeric_query_does_not_expand_standalone_numeric_search_term(self):
        plan = build_text_search_plan("b 30")

        self.assertEqual(plan["query_normalized"], "b 30")
        self.assertNotIn("30", plan["extra_terms"])
        self.assertNotIn("30", plan["fallback_tokens"])

    def test_numeric_only_query_can_expand_numeric_search_term(self):
        plan = build_text_search_plan("530")

        self.assertIn("530", plan["fallback_tokens"])


if __name__ == "__main__":
    unittest.main()

import unittest

from backend.keyword_search_filters import _should_ignore_keyword_search_query


class KeywordSearchFiltersTestCase(unittest.TestCase):
    def test_split_numeric_expression_query_is_ignored(self):
        self.assertTrue(_should_ignore_keyword_search_query("1+1"))
        self.assertTrue(_should_ignore_keyword_search_query("1 1"))

    def test_contiguous_numeric_query_is_still_allowed(self):
        self.assertFalse(_should_ignore_keyword_search_query("111"))


if __name__ == "__main__":
    unittest.main()

import re


KEYWORD_SEARCH_MEANINGLESS_PATTERNS = {'ok', 'no', 'yes', 'hi', 'hey', 'lol', 'lmao', 'wtf', 'omg', 'bruh'}


def _should_ignore_keyword_search_query(search_query):
    """过滤明显无效的关键词查询，同时允许较长的纯数字关键词。"""
    normalized_query = re.sub(r'\s+', ' ', str(search_query or '')).strip()
    if not normalized_query:
        return True

    if len(normalized_query) < 2:
        return True

    compact_query = normalized_query.replace(' ', '')
    if compact_query.isdigit():
        if compact_query != normalized_query:
            return True
        return len(compact_query) < 3

    return normalized_query.lower() in KEYWORD_SEARCH_MEANINGLESS_PATTERNS

import re


KEYWORD_SEARCH_MEANINGLESS_PATTERNS = {'ok', 'no', 'yes', 'hi', 'hey', 'lol', 'lmao', 'wtf', 'omg', 'bruh'}


def _should_ignore_keyword_search_query(search_query):
    """过滤明显无效的关键词查询，同时允许较长的纯数字关键词。"""
    normalized_query = re.sub(r'\s+', ' ', str(search_query or '')).strip()
    if not normalized_query:
        return True

    if len(normalized_query) < 2:
        return True

    if re.fullmatch(r'[\d\s+\-*/.:]+', normalized_query):
        digit_groups = re.findall(r'\d+', normalized_query)
        if len(digit_groups) != 1:
            return True
        compact_query = digit_groups[0]
        if compact_query != normalized_query:
            return True
        return len(compact_query) < 3

    compact_query = normalized_query.replace(' ', '')
    if compact_query.isdigit():
        return True

    return normalized_query.lower() in KEYWORD_SEARCH_MEANINGLESS_PATTERNS

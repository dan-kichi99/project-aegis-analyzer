from app.knowledge.query_stopword_filter import QueryStopwordFilter


def test_filter_general_stopwords():
    sw_filter = QueryStopwordFilter()
    tokens = ["the", "rsa", "and", "fermat"]
    assert sw_filter.filter(tokens) == ["rsa", "fermat"]


def test_filter_preserves_order():
    sw_filter = QueryStopwordFilter()
    tokens = ["this", "jwt", "is", "for", "web", "token"]
    assert sw_filter.filter(tokens) == ["jwt", "web", "token"]


def test_filter_empty_list():
    sw_filter = QueryStopwordFilter()
    assert sw_filter.filter([]) == []


def test_filter_only_stopwords():
    sw_filter = QueryStopwordFilter()
    tokens = ["the", "and", "this", "problem", "using"]
    assert sw_filter.filter(tokens) == []


def test_filter_preserves_important_ctf_words():
    sw_filter = QueryStopwordFilter()
    important_words = ["rsa", "jwt", "web", "ghidra", "xor", "sql", "aes"]
    assert sw_filter.filter(important_words) == important_words


def test_filter_preserves_duplicates_for_non_stopwords():
    sw_filter = QueryStopwordFilter()
    tokens = ["the", "rsa", "rsa", "and", "fermat", "fermat"]
    assert sw_filter.filter(tokens) == ["rsa", "rsa", "fermat", "fermat"]

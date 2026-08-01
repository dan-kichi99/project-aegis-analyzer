from app.knowledge.knowledge_budget_limiter import KnowledgeBudgetLimiter


def test_limit_empty_list():
    limiter = KnowledgeBudgetLimiter()
    assert limiter.limit([]) == []


def test_limit_single_chunk_under_limit():
    limiter = KnowledgeBudgetLimiter()
    chunk = "A" * 1500
    result = limiter.limit([chunk])
    assert len(result) == 1
    assert result[0] == chunk


def test_limit_multiple_chunks_under_limit():
    limiter = KnowledgeBudgetLimiter()
    c1 = "A" * 1000
    c2 = "B" * 1000
    c3 = "C" * 1000
    result = limiter.limit([c1, c2, c3])
    assert len(result) == 3
    assert result == [c1, c2, c3]


def test_limit_exceeding_subsequent_chunks_excluded():
    limiter = KnowledgeBudgetLimiter()
    c1 = "A" * 1200
    c2 = "B" * 1200
    c3 = "C" * 1200  # 1200 + 1200 + 1200 = 3600 > 3000
    result = limiter.limit([c1, c2, c3])
    assert len(result) == 2
    assert result == [c1, c2]


def test_limit_first_chunk_exceeds_truncated():
    limiter = KnowledgeBudgetLimiter()
    c1 = "A" * 4000
    result = limiter.limit([c1])
    assert len(result) == 1
    assert len(result[0]) == 3000
    assert result[0] == "A" * 3000


def test_limit_skips_empty_and_whitespace_chunks():
    limiter = KnowledgeBudgetLimiter()
    c1 = "A" * 1000
    c2 = ""
    c3 = "   "
    c4 = "B" * 1000
    result = limiter.limit([c1, c2, c3, c4])
    assert len(result) == 2
    assert result == [c1, c4]


def test_limit_preserves_input_order():
    limiter = KnowledgeBudgetLimiter()
    c1 = "First chunk text " * 50
    c2 = "Second chunk text " * 50
    result = limiter.limit([c1, c2])
    assert result[0] == c1
    assert result[1] == c2

from app.knowledge.query_expander import QueryExpander


def test_expand_fermat_rule():
    expander = QueryExpander()
    res = expander.expand("RSA modulus factors are almost the same size")
    assert "fermat" in res
    assert "factorization" in res


def test_expand_jwt_rule():
    expander = QueryExpander()
    res = expander.expand("unsigned token algorithm set to none on web session")
    assert "jwt" in res
    assert "json" in res
    assert "web" in res
    assert "token" in res


def test_expand_ghidra_rule():
    expander = QueryExpander()
    res = expander.expand("decompiler shows C pseudocode cross references")
    assert "ghidra" in res
    assert "reverse" in res
    assert "engineering" in res


def test_expand_xor_rule():
    expander = QueryExpander()
    res = expander.expand("bitwise operation applied with constant byte array")
    assert "xor" in res
    assert "encryption" in res


def test_expand_no_match():
    expander = QueryExpander()
    query = "unrelated query about SQL injection"
    res = expander.expand(query)
    assert res == query


def test_expand_multiple_rules_match():
    expander = QueryExpander()
    query = "decompiler shows bitwise operation"
    res = expander.expand(query)
    assert "ghidra" in res
    assert "xor" in res


def test_no_duplicate_expansions():
    expander = QueryExpander()
    query = "decompiler with c pseudocode"
    res = expander.expand(query)
    words = res.split()
    assert words.count("ghidra") == 1


def test_expand_empty_query():
    expander = QueryExpander()
    assert expander.expand("") == ""
    assert expander.expand("   ") == "   "

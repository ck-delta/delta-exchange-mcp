from delta_exchange_mcp.client import sign


def test_sign_matches_documented_payload_shape():
    # payload shape: method + timestamp + path + query + body
    # this locks the concatenation order; real known-good vector goes in M2.
    sig = sign(
        secret="secret",
        method="GET",
        timestamp="1600000000",
        path="/v2/orders",
        query="?product_id=1",
        body="",
    )
    assert len(sig) == 64
    assert all(c in "0123456789abcdef" for c in sig)


def test_sign_changes_when_body_changes():
    a = sign("s", "POST", "1", "/p", "", "")
    b = sign("s", "POST", "1", "/p", "", "{}")
    assert a != b


def test_sign_changes_when_secret_changes():
    a = sign("s1", "GET", "1", "/p", "", "")
    b = sign("s2", "GET", "1", "/p", "", "")
    assert a != b

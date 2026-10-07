"""Accès à l'interface (wallet D-021, D-035)."""

from wallet_crypto import auth


def test_host_header_loopback():
    for h in ("127.0.0.1:8090", "localhost:8090", "localhost", "[::1]:8090", "LOCALHOST:1", "127.0.0.5"):
        assert auth.host_header_is_loopback(h), h
    for h in ("", "attaquant.example", "attaquant.example:8090", "192.168.1.10:8090", "[fe80::1]:80"):
        assert not auth.host_header_is_loopback(h), h


def test_session_token_changes_with_password():
    a = auth.session_token("secret", auth.hash_password("motdepasse-1"))
    b = auth.session_token("secret", auth.hash_password("motdepasse-1"))  # autre sel
    assert a != b
    assert auth.session_token("s1", "x") != auth.session_token("s2", "x")
    assert auth.session_token("s", "x") == auth.session_token("s", "x")


def test_login_throttle():
    t = auth.LoginThrottle(free=3, base_s=30, max_s=100)
    for _ in range(2):
        t.failed(0)
    assert t.wait_s(0) == 0
    t.failed(0)
    assert t.wait_s(0) == 30
    t.failed(10)
    assert t.wait_s(10) == 60
    t.failed(10)
    t.failed(10)
    assert t.wait_s(10) == 100  # plafond
    t.succeeded()
    assert t.wait_s(10) == 0

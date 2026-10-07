"""Compteur de requêtes par service (wallet D-036)."""

from wallet_crypto.sources import http as http_mod
from wallet_crypto.sources.http import Http, call_label, is_alchemy

KEY = "cle-alchemy-secrete-123"


def test_call_labels_never_contain_the_key():
    portfolio = call_label("POST", f"https://api.g.alchemy.com/data/v1/{KEY}/assets/tokens/by-address", {})
    rpc = call_label("POST", f"https://opt-mainnet.g.alchemy.com/v2/{KEY}", {"method": "eth_call"})
    assert portfolio == "Alchemy · Portfolio assets/tokens/by-address"
    assert rpc == "Alchemy · opt-mainnet · eth_call"
    assert KEY not in portfolio + rpc
    assert is_alchemy(portfolio) and is_alchemy(rpc)
    hl = call_label("POST", "https://api.hyperliquid.xyz/info", {"type": "userFillsByTime"})
    assert hl == "Hyperliquid · userFillsByTime" and not is_alchemy(hl)
    assert call_label("GET", "https://api.binance.com/api/v3/klines") == "Binance · klines"


class _Resp:
    def __init__(self, status, body="{}"):
        self.status_code, self.text = status, body

    def json(self, parse_float=None):
        return {}


def test_retries_are_counted(monkeypatch):
    h = Http(secrets=[KEY], retries=2, backoff=0)
    answers = iter([_Resp(429), _Resp(200)])
    monkeypatch.setattr(h.session, "request", lambda *a, **k: next(answers))
    monkeypatch.setattr(http_mod.time, "sleep", lambda s: None)
    h.post_json(f"https://opt-mainnet.g.alchemy.com/v2/{KEY}", {"method": "eth_call"})
    assert h.calls == {"Alchemy · opt-mainnet · eth_call": 2}

from decimal import Decimal

import pytest
import requests

from wallet_crypto.sources.http import Http, HttpError


class FakeResponse:
    def __init__(self, status, text):
        self.status_code = status
        self.text = text

    def json(self, **kw):
        import json

        return json.loads(self.text, **kw)


def test_http_retry_decimal_and_mask(monkeypatch):
    calls = []
    answers = [FakeResponse(429, ""), FakeResponse(200, '{"price": 0.1}')]

    def request(method, url, timeout, **kw):
        calls.append(url)
        return answers.pop(0)

    h = Http(["SECRETKEY99"], backoff=0)
    monkeypatch.setattr(h.session, "request", request)
    assert h.get_json("https://x/SECRETKEY99") == {"price": Decimal("0.1")}
    assert len(calls) == 2

    monkeypatch.setattr(h.session, "request", lambda *a, **k: FakeResponse(401, "bad key SECRETKEY99"))
    with pytest.raises(HttpError) as exc:
        h.post_json("https://x/v2/SECRETKEY99", {})
    assert "SECRETKEY99" not in str(exc.value) and "HTTP 401" in str(exc.value)

    def boom(*a, **k):
        raise requests.ConnectionError("refused https://x/SECRETKEY99")

    monkeypatch.setattr(h.session, "request", boom)
    with pytest.raises(HttpError) as exc:
        h.get_json("https://x/SECRETKEY99")
    assert "SECRETKEY99" not in str(exc.value)

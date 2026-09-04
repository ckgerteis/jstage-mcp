"""Error classification: J-STAGE answering with an error status is API_ERROR;
failing to reach J-STAGE is TRANSPORT_ERROR. Run with pytest, or directly."""
from __future__ import annotations

import sys

import httpx

from jstage_mcp.server import _error_diag


def _status_error(code: int) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", "https://api.jstage.jst.go.jp/searchapi/do")
    return httpx.HTTPStatusError("x", request=req, response=httpx.Response(code, request=req))


def test_http_status_is_api_error():
    for code in (400, 404, 500, 503):
        d = _error_diag(_status_error(code))
        assert d["code"] == "API_ERROR", (code, d)
        assert str(code) in d["message"]


def test_transport_failures_are_transport_error():
    req = httpx.Request("GET", "https://api.jstage.jst.go.jp/searchapi/do")
    for exc in (httpx.ConnectTimeout("t", request=req), httpx.ConnectError("c", request=req),
                httpx.ReadTimeout("r", request=req)):
        assert _error_diag(exc)["code"] == "TRANSPORT_ERROR", exc


def test_malformed_answer_is_api_error():
    assert _error_diag(KeyError("result"))["code"] == "API_ERROR"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok  ", name)
    sys.exit(0)

"""A 200 that is not an Atom feed is an outage, not an empty result.

Stress test, 12 October 2026: an XHTML "503 Service Unavailable" page, or a
feed with its namespaces stripped, served with status 200, parsed as a feed
with no entries. Search reported LITERAL_COMPOUND_EMPTY ("try another
rendering before concluding the literature is absent") and list_issues
reported total_results 0 with no error.
"""
import asyncio
import json
from pathlib import Path

import pytest

from jstage_mcp import server

REAL = (Path(__file__).parent / "fixtures" / "search_text_bosozoku.xml").read_text(encoding="utf-8")

NOT_FEEDS = [
    '<html xmlns="http://www.w3.org/1999/xhtml"><body><h1>503 Service Unavailable</h1></body></html>',
    "<feed><totalResults>5</totalResults><entry><title>x</title></entry></feed>",
    "<response/>",
]


def _run(monkeypatch, body, coro):
    async def fake_get(_params):
        return body
    monkeypatch.setattr(server, "_get", fake_get)
    monkeypatch.setattr(server, "MIN_REQUEST_INTERVAL", 0, raising=False)
    return json.loads(asyncio.run(coro))


@pytest.mark.parametrize("body", NOT_FEEDS)
def test_search_reports_api_error(monkeypatch, body):
    out = _run(monkeypatch, body, server.jstage_search_articles(
        server.SearchArticlesInput(text="暴走族")))
    codes = [d["code"] for d in out["diagnostics"]]
    assert "API_ERROR" in codes and "LITERAL_COMPOUND_EMPTY" not in codes


@pytest.mark.parametrize("body", NOT_FEEDS)
def test_list_issues_reports_an_error(monkeypatch, body):
    out = _run(monkeypatch, body, server.jstage_list_issues(
        server.ListIssuesInput(material="社会学評論")))
    assert out.get("error")


def test_real_feed_still_parses():
    meta, items, warning = server._parse_articles(REAL, "fulltext")
    assert warning is None and meta["total"] > 0 and len(items) == 2

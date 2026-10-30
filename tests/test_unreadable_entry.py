"""One entry that will not build is left out and named; the page survives.

The RECORD_UNREADABLE repair of 12 Oct 2026 reached every server but jstage, whose
parser built the page in one list comprehension: a single entry that raised
turned the whole page into API_ERROR. Also: a count field of thousands of
digits (int() raises on Python 3.11+) no longer sinks the page.
"""
import asyncio
import json

import pytest

from jstage_mcp import server
from test_doi_and_year import FEED_HEAD, _entry, _volume

_real = server._entry_to_item


def _break(numbers):
    """Make _entry_to_item raise on the entries whose DOI ends in one of `numbers`."""
    def build(entry, matched_in):
        doi = server._text(entry.find("prism:doi", server.NS)) or ""
        if any(doi.endswith(f"_{n}") for n in numbers):
            raise TypeError("malformed")
        return _real(entry, matched_in)
    return build


def _page(n):
    body = "".join(_entry(i) for i in range(1, n + 1))
    return FEED_HEAD + f"<opensearch:totalResults>{n}</opensearch:totalResults>{body}</feed>"


def _search(monkeypatch, xml):
    async def fake_get(params):
        return xml
    monkeypatch.setattr(server, "_get", fake_get)
    env = json.loads(asyncio.run(server.jstage_search_articles(server.SearchArticlesInput(text="青年団"))))
    return env, [d["code"] for d in env["diagnostics"]]


def test_one_bad_entry_is_skipped_and_named(monkeypatch):
    monkeypatch.setattr(server, "_entry_to_item", _break([2]))
    env, codes = _search(monkeypatch, _page(3))
    assert "API_ERROR" not in codes and "RECORD_UNREADABLE" in codes
    assert [it["ids"]["doi"] for it in env["items"]] == ["10.1/abc.1.0_1", "10.1/abc.1.0_3"]
    msg = next(d["message"] for d in env["diagnostics"] if d["code"] == "RECORD_UNREADABLE")
    assert "1 of 3" in msg and "#2 (10.1/abc.1.0_2)" in msg


def test_a_page_of_only_bad_entries_is_not_an_absence(monkeypatch):
    monkeypatch.setattr(server, "_entry_to_item", _break([1, 2]))
    env, codes = _search(monkeypatch, _page(2))
    assert codes[0] == "RECORD_UNREADABLE" and "LITERAL_COMPOUND_EMPTY" not in codes
    assert env["items"] == [] and env["result"]["total"] == 2


@pytest.mark.parametrize("bad", ["9" * 5000, "abc", "-3", "１e3"])
def test_unreadable_total_does_not_sink_the_page(monkeypatch, bad):
    xml = _page(2).replace("<opensearch:totalResults>2</opensearch:totalResults>",
                           f"<opensearch:totalResults>{bad}</opensearch:totalResults>")
    env, codes = _search(monkeypatch, xml)
    assert "API_ERROR" not in codes and len(env["items"]) == 2


def test_huge_year_is_dropped_not_fatal(monkeypatch):
    xml = _page(1).replace("<pubyear>2020</pubyear>", "<pubyear>" + "9" * 5000 + "</pubyear>")
    env, codes = _search(monkeypatch, xml)
    assert "API_ERROR" not in codes and env["items"][0]["source"]["year"] is None


def test_doi_absence_is_not_claimed_when_an_entry_was_unreadable(monkeypatch):
    fake_get, _ = _volume(3)
    monkeypatch.setattr(server, "_get", fake_get)
    monkeypatch.setattr(server, "_entry_to_item", _break([2]))
    env = json.loads(asyncio.run(server.jstage_get_article_by_doi(
        server.GetArticleByDoiInput(doi="10.1/abc.1.0_2"))))
    codes = [d["code"] for d in env["diagnostics"]]
    assert codes[0] == "RECORD_UNREADABLE" and "may be among them" in env["diagnostics"][0]["message"]

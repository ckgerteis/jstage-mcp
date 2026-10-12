"""jstage_get_article_by_doi pages through the volume; a stray year character
does not sink a page (stress test, 12 October 2026).

The DOI lookup asked for one page of 100 entries in the volume and matched
the DOI against those only, so any article after the hundredth came back as
"no entry matched exactly". And `str.isdigit()` is true for characters such
as '²' that int() rejects, so one such <pubyear> turned a whole page into
API_ERROR.
"""
import asyncio
import json

import pytest

from jstage_mcp import server

FEED_HEAD = ('<feed xmlns="http://www.w3.org/2005/Atom" '
             'xmlns:prism="http://prismstandard.org/namespaces/basic/2.0/" '
             'xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">'
             "<result><status>0</status><message/></result>")


def _entry(i, year="2020"):
    return (f"<entry><article_title><en>Article {i}</en><ja/></article_title>"
            f"<prism:volume>1</prism:volume><prism:number>0</prism:number>"
            f"<pubyear>{year}</pubyear><prism:doi>10.1/abc.1.0_{i}</prism:doi></entry>")


def _volume(n, year_of=lambda i: "2020"):
    """A fake API over a volume of n articles, honouring start and count."""
    calls = []

    async def fake_get(params):
        calls.append(dict(params))
        start, count = int(params.get("start", 1)), int(params["count"])
        page = range(start, min(start + count, n + 1))
        body = "".join(_entry(i, year_of(i)) for i in page)
        return (FEED_HEAD + f"<opensearch:totalResults>{n}</opensearch:totalResults>"
                f"<opensearch:startIndex>{start}</opensearch:startIndex>{body}</feed>")
    return fake_get, calls


@pytest.fixture(autouse=True)
def no_throttle(monkeypatch):
    monkeypatch.setattr(server, "MIN_REQUEST_INTERVAL", 0)


def _lookup(monkeypatch, n, doi, **kw):
    get, calls = _volume(n, **kw)
    monkeypatch.setattr(server, "_get", get)
    out = json.loads(asyncio.run(server.jstage_get_article_by_doi(
        server.GetArticleByDoiInput(doi=doi))))
    return out, calls


def test_article_past_the_first_hundred_is_found(monkeypatch):
    out, calls = _lookup(monkeypatch, 250, "10.1/abc.1.0_230")
    assert out["result"]["total"] == 1
    assert out["items"][0]["ids"]["doi"] == "10.1/abc.1.0_230"
    assert [c.get("start", 1) for c in calls] == [1, 101, 201]


def test_lookup_stops_paging_once_found(monkeypatch):
    _, calls = _lookup(monkeypatch, 250, "10.1/abc.1.0_5")
    assert len(calls) == 1


def test_absent_doi_reads_the_whole_volume_then_says_so(monkeypatch):
    out, calls = _lookup(monkeypatch, 150, "10.1/abc.1.0_999")
    assert out["result"]["total"] == 0 and len(calls) == 2
    assert "150" in out["diagnostics"][0]["message"]


def test_lookup_is_capped_and_says_how_far_it_looked(monkeypatch):
    n = 100 * server.DOI_LOOKUP_MAX_PAGES + 50
    out, calls = _lookup(monkeypatch, n, f"10.1/abc.1.0_{n}")
    assert len(calls) == server.DOI_LOOKUP_MAX_PAGES
    msg = out["diagnostics"][0]["message"]
    assert out["result"]["total"] == 0
    assert str(100 * server.DOI_LOOKUP_MAX_PAGES) in msg and str(n) in msg


@pytest.mark.parametrize("year", ["²", "٢٠٢٠x", "２０２０"])
def test_odd_pubyear_does_not_sink_the_page(monkeypatch, year):
    out, _ = _lookup(monkeypatch, 3, "10.1/abc.1.0_2",
                     year_of=lambda i: year if i == 1 else "2020")
    assert out["result"]["total"] == 1
    assert "API_ERROR" not in [d["code"] for d in out["diagnostics"]]


def test_full_width_year_digits_are_read():
    meta, items, _ = server._parse_articles(
        FEED_HEAD + "<opensearch:totalResults>1</opensearch:totalResults>"
        + _entry(1, "２０２０") + "</feed>", "metadata")
    assert items[0]["source"]["year"] == 2020

"""J-STAGE MCP server.

A FastMCP stdio server exposing the J-STAGE WebAPI
(https://api.jstage.jst.go.jp/searchapi/do) for searching Japanese
academic articles and journals.

Tool surface:
    - jstage_search_articles  : full-text/author/title/journal search
    - jstage_list_issues      : volumes & issues for a known title/ISSN
    - jstage_search_journals  : find journals by title/ISSN/publisher
                                (currently a service=2 fallback because
                                service=4 is documented but not live)
    - jstage_get_article_by_doi : single-article lookup, with DOI parsing

J-STAGE attribution requirement: every response includes a
"powered_by" key per the JST Terms of Use.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from enum import Enum
from typing import Any, Optional
from xml.etree import ElementTree as ET

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

API_BASE = "https://api.jstage.jst.go.jp/searchapi/do"
USER_AGENT = "jstage-mcp/0.1 (research; +https://www.jstage.jst.go.jp)"
DEFAULT_TIMEOUT = 30.0
MIN_REQUEST_INTERVAL = 1.0  # seconds — be polite, JST forbids bulk downloads
ATTRIBUTION = "Powered by J-STAGE (https://www.jstage.jst.go.jp/)"

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "prism": "http://prismstandard.org/namespaces/basic/2.0/",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}

# DOIs issued through J-STAGE follow this pattern:
#   10.<registrant>/<cdjournal>.<vol>.<no>_<page>
# e.g. 10.51112/istd.5.0_112  -> cdjournal=istd, vol=5, no=0, page=112
JSTAGE_DOI_RE = re.compile(
    r"^10\.\d+/(?P<cdjournal>[A-Za-z][A-Za-z0-9]*)"
    r"\.(?P<vol>\d+)\.(?P<no>\d+)_(?P<page>\d+)$"
)

# ---------------------------------------------------------------------------
# Polite rate limiter
# ---------------------------------------------------------------------------

_rate_lock = asyncio.Lock()
_last_request_at = 0.0


async def _throttle() -> None:
    """Ensure at least MIN_REQUEST_INTERVAL between outbound requests."""
    global _last_request_at
    async with _rate_lock:
        now = time.monotonic()
        wait = MIN_REQUEST_INTERVAL - (now - _last_request_at)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_at = time.monotonic()


# ---------------------------------------------------------------------------
# HTTP + XML
# ---------------------------------------------------------------------------


async def _get(params: dict[str, Any]) -> str:
    """Issue a throttled GET to the J-STAGE search API."""
    await _throttle()
    clean = {k: v for k, v in params.items() if v is not None and v != ""}
    headers = {"User-Agent": USER_AGENT, "Accept": "application/atom+xml"}
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        resp = await client.get(API_BASE, params=clean, headers=headers)
        resp.raise_for_status()
        return resp.text


def _text(elem: Optional[ET.Element]) -> Optional[str]:
    if elem is None:
        return None
    txt = elem.text
    return txt.strip() if isinstance(txt, str) else None


def _bilingual(parent: ET.Element, tag: str) -> dict[str, Optional[str]]:
    """Read a {tag}/{en,ja} structure into {'en': ..., 'ja': ...}."""
    block = parent.find(f"atom:{tag}", NS)
    if block is None:
        return {"en": None, "ja": None}
    return {
        "en": _text(block.find("atom:en", NS)),
        "ja": _text(block.find("atom:ja", NS)),
    }


def _bilingual_link(parent: ET.Element, tag: str) -> dict[str, Optional[str]]:
    """vols_link / article_link have plain en/ja URL text, no nesting."""
    block = parent.find(f"atom:{tag}", NS)
    if block is None:
        return {"en": None, "ja": None}
    return {
        "en": _text(block.find("atom:en", NS)),
        "ja": _text(block.find("atom:ja", NS)),
    }


def _authors(entry: ET.Element) -> list[dict[str, Optional[str]]]:
    """Extract authors as a list of {'en': ..., 'ja': ...}."""
    authors: list[dict[str, Optional[str]]] = []
    for author in entry.findall("atom:author", NS):
        en_block = author.find("atom:en", NS)
        ja_block = author.find("atom:ja", NS)
        en_names = (
            [_text(n) for n in en_block.findall("atom:name", NS)] if en_block is not None else []
        )
        ja_names = (
            [_text(n) for n in ja_block.findall("atom:name", NS)] if ja_block is not None else []
        )
        # Multiple co-authors can sit inside one <author> block as repeated <name>s.
        # Pair them positionally; fill missing with None.
        n = max(len(en_names), len(ja_names), 1)
        for i in range(n):
            authors.append(
                {
                    "en": en_names[i] if i < len(en_names) else None,
                    "ja": ja_names[i] if i < len(ja_names) else None,
                }
            )
    # Drop completely empty entries.
    return [a for a in authors if a["en"] or a["ja"]]


def _publisher(entry: ET.Element) -> dict[str, Any]:
    """Service=2 entries embed publisher info."""
    pub = entry.find("atom:publisher", NS)
    if pub is None:
        return {}
    return {
        "name": _bilingual(pub, "name"),
        "url": _bilingual(pub, "url"),
    }


def _check_status(root: ET.Element) -> None:
    """Raise ValueError if the API returned an error status."""
    result = root.find("atom:result", NS)
    if result is None:
        return
    status = _text(result.find("atom:status", NS))
    message = _text(result.find("atom:message", NS))
    if status and status != "0":
        raise ValueError(f"J-STAGE API error {status}: {message or '(no message)'}")


def _parse_meta(root: ET.Element) -> dict[str, Any]:
    return {
        "total_results": int(_text(root.find("opensearch:totalResults", NS)) or 0),
        "start_index": int(_text(root.find("opensearch:startIndex", NS)) or 0),
        "items_per_page": int(_text(root.find("opensearch:itemsPerPage", NS)) or 0),
        "updated": _text(root.find("atom:updated", NS)),
    }


def _parse_article_entry(entry: ET.Element) -> dict[str, Any]:
    return {
        "title": _bilingual(entry, "article_title"),
        "url": _bilingual_link(entry, "article_link"),
        "authors": _authors(entry),
        "journal": {
            "title": _bilingual(entry, "material_title"),
            "cdjournal": _text(entry.find("atom:cdjournal", NS)),
            "issn": _text(entry.find("prism:issn", NS)),
            "eissn": _text(entry.find("prism:eIssn", NS)),
        },
        "volume": _text(entry.find("prism:volume", NS)),
        "number": _text(entry.find("prism:number", NS)),
        "page_start": _text(entry.find("prism:startingPage", NS)),
        "page_end": _text(entry.find("prism:endingPage", NS)),
        "pubyear": _text(entry.find("atom:pubyear", NS)),
        "doi": _text(entry.find("prism:doi", NS)),
        "updated": _text(entry.find("atom:updated", NS)),
    }


def _parse_volume_entry(entry: ET.Element) -> dict[str, Any]:
    return {
        "label": _bilingual(entry, "vols_title"),
        "url": _bilingual_link(entry, "vols_link"),
        "journal": {
            "title": _bilingual(entry, "material_title"),
            "cdjournal": _text(entry.find("atom:cdjournal", NS)),
            "issn": _text(entry.find("prism:issn", NS)),
            "eissn": _text(entry.find("prism:eIssn", NS)),
        },
        "publisher": _publisher(entry),
        "volume": _text(entry.find("prism:volume", NS)),
        "page_start": _text(entry.find("prism:startingPage", NS)),
        "page_end": _text(entry.find("prism:endingPage", NS)),
        "pubyear": _text(entry.find("atom:pubyear", NS)),
        "updated": _text(entry.find("atom:updated", NS)),
    }


def _parse_feed(xml_text: str, kind: str) -> dict[str, Any]:
    """Parse an Atom feed into a structured dict.

    `kind` is "article" or "volume" — selects the entry parser.
    """
    root = ET.fromstring(xml_text)
    _check_status(root)
    meta = _parse_meta(root)
    parser = _parse_article_entry if kind == "article" else _parse_volume_entry
    entries = [parser(e) for e in root.findall("atom:entry", NS)]
    # The API returns a single empty <entry/> on zero hits — strip those.
    entries = [e for e in entries if any(v for v in e.values() if v not in (None, {}, []))]
    return {**meta, "entries": entries, "powered_by": ATTRIBUTION}


# ---------------------------------------------------------------------------
# Pydantic input models
# ---------------------------------------------------------------------------


class _Base(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="forbid",
    )


class SearchArticlesInput(_Base):
    text: Optional[str] = Field(
        default=None,
        description="Full-text keyword (searches title, abstract, body). "
        "Japanese or English. English terms are translated by J-STAGE's "
        "internal dictionary; Japanese terms are matched directly.",
    )
    article: Optional[str] = Field(
        default=None, description="Article title (substring match)."
    )
    author: Optional[str] = Field(
        default=None, description="Author name in Japanese or romanized English."
    )
    affil: Optional[str] = Field(
        default=None, description="Author affiliation."
    )
    keyword: Optional[str] = Field(
        default=None, description="Author-supplied keywords."
    )
    abst: Optional[str] = Field(
        default=None, description="Search the abstract field only."
    )
    material: Optional[str] = Field(
        default=None, description="Journal (material) title."
    )
    issn: Optional[str] = Field(
        default=None,
        description="Journal ISSN, with or without hyphen (e.g. 2185-4432).",
    )
    cdjournal: Optional[str] = Field(
        default=None,
        description="J-STAGE journal code (e.g. 'istd'). Visible in J-STAGE URLs.",
    )
    vol: Optional[str] = Field(default=None, description="Volume number filter.")
    no: Optional[str] = Field(default=None, description="Issue number filter.")
    pubyearfrom: Optional[int] = Field(
        default=None, description="Earliest publication year (inclusive).", ge=1900, le=2100
    )
    pubyearto: Optional[int] = Field(
        default=None, description="Latest publication year (inclusive).", ge=1900, le=2100
    )
    count: int = Field(
        default=20, description="Number of results per page (1–100).", ge=1, le=100
    )
    start: int = Field(
        default=1, description="1-indexed start position for pagination.", ge=1
    )

    @field_validator("text", "article", "author", "affil", "keyword", "abst", "material")
    @classmethod
    def _non_empty_if_present(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        if not v.strip():
            return None
        return v


class ListIssuesInput(_Base):
    material: Optional[str] = Field(
        default=None, description="Journal title (substring)."
    )
    issn: Optional[str] = Field(
        default=None, description="Journal ISSN (with or without hyphen)."
    )
    cdjournal: Optional[str] = Field(
        default=None, description="J-STAGE journal code."
    )
    pubyearfrom: Optional[int] = Field(
        default=None, ge=1900, le=2100,
        description="Earliest publication year (inclusive).",
    )
    pubyearto: Optional[int] = Field(
        default=None, ge=1900, le=2100,
        description="Latest publication year (inclusive).",
    )
    count: int = Field(default=20, ge=1, le=100)
    start: int = Field(default=1, ge=1)


class SearchJournalsInput(_Base):
    material: Optional[str] = Field(
        default=None, description="Journal title (substring)."
    )
    issn: Optional[str] = Field(
        default=None, description="Journal ISSN."
    )
    publisher: Optional[str] = Field(
        default=None,
        description=(
            "Publisher name. Note: filtering by publisher is not supported by "
            "the current fallback (service=2); this field is accepted for "
            "forward compatibility with service=4 once JST activates it."
        ),
    )
    pubyearfrom: Optional[int] = Field(default=None, ge=1900, le=2100)
    pubyearto: Optional[int] = Field(default=None, ge=1900, le=2100)
    count: int = Field(default=20, ge=1, le=100)


class GetArticleByDoiInput(_Base):
    doi: str = Field(
        ...,
        description="DOI string, with or without doi.org prefix "
        "(e.g. '10.51112/istd.5.0_112').",
        min_length=5,
    )


# ---------------------------------------------------------------------------
# Error helper
# ---------------------------------------------------------------------------


def _format_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return json.dumps(
            {
                "error": "http_error",
                "status_code": exc.response.status_code,
                "message": f"J-STAGE returned HTTP {exc.response.status_code}.",
                "powered_by": ATTRIBUTION,
            }
        )
    if isinstance(exc, httpx.TimeoutException):
        return json.dumps(
            {"error": "timeout", "message": "Request to J-STAGE timed out.",
             "powered_by": ATTRIBUTION}
        )
    if isinstance(exc, ValueError):
        return json.dumps(
            {"error": "api_error", "message": str(exc), "powered_by": ATTRIBUTION}
        )
    return json.dumps(
        {"error": type(exc).__name__, "message": str(exc), "powered_by": ATTRIBUTION}
    )


# ---------------------------------------------------------------------------
# DOI helpers
# ---------------------------------------------------------------------------


def _strip_doi_prefix(doi: str) -> str:
    doi = doi.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:", "DOI:"):
        if doi.startswith(prefix):
            return doi[len(prefix) :]
    return doi


# ---------------------------------------------------------------------------
# Server + tools
# ---------------------------------------------------------------------------

mcp = FastMCP("jstage_mcp")


@mcp.tool(
    name="jstage_search_articles",
    annotations={
        "title": "Search J-STAGE articles",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def jstage_search_articles(params: SearchArticlesInput) -> str:
    """Search articles published on J-STAGE.

    Returns up to `count` matching articles with bilingual (English/Japanese)
    titles, authors, journal metadata, DOI, volume/issue/pages, and
    publication year. Combine fields freely; all are AND-ed by the API.

    Pagination: pass `start` and `count`. Total hit count is returned in
    `total_results`.

    Returns:
        JSON string with keys: total_results, start_index, items_per_page,
        updated, entries (list of articles), powered_by.
    """
    payload = params.model_dump(exclude_none=True)
    payload["service"] = 3
    try:
        xml_text = await _get(payload)
        parsed = _parse_feed(xml_text, "article")
    except Exception as exc:  # noqa: BLE001
        return _format_error(exc)
    return json.dumps(parsed, ensure_ascii=False, indent=2)


@mcp.tool(
    name="jstage_list_issues",
    annotations={
        "title": "List volumes & issues of a J-STAGE journal",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def jstage_list_issues(params: ListIssuesInput) -> str:
    """Return the volume/issue spine of a journal on J-STAGE.

    Identify the journal by `material` (title), `issn`, or `cdjournal`
    (J-STAGE's internal journal code). At least one identifier should be
    provided in practice; without one the API returns the full catalog.

    Returns:
        JSON string with keys: total_results, start_index, items_per_page,
        updated, entries (list of volumes with publisher/journal metadata),
        powered_by.
    """
    payload = params.model_dump(exclude_none=True)
    payload["service"] = 2
    try:
        xml_text = await _get(payload)
        parsed = _parse_feed(xml_text, "volume")
    except Exception as exc:  # noqa: BLE001
        return _format_error(exc)
    return json.dumps(parsed, ensure_ascii=False, indent=2)


def _dedupe_journals(volume_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse volume entries to one record per journal."""
    seen: dict[str, dict[str, Any]] = {}
    for entry in volume_entries:
        journal = entry.get("journal", {}) or {}
        key = journal.get("cdjournal") or journal.get("issn") or json.dumps(journal.get("title"))
        if not key or key in seen:
            continue
        seen[key] = {
            "title": journal.get("title"),
            "cdjournal": journal.get("cdjournal"),
            "issn": journal.get("issn"),
            "eissn": journal.get("eissn"),
            "publisher": entry.get("publisher", {}),
        }
    return list(seen.values())


@mcp.tool(
    name="jstage_search_journals",
    annotations={
        "title": "Search J-STAGE journals",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def jstage_search_journals(params: SearchJournalsInput) -> str:
    """Find journals on J-STAGE by title, ISSN, or publisher.

    Implementation note: J-STAGE announced a journal-search endpoint
    (service=4) on 26 March 2026, but the public API currently rejects
    that service code. This tool first probes service=4; if unavailable
    it falls back to service=2 (volume search) and deduplicates the
    response into journal-level records (title, ISSN, publisher). When
    JST activates service=4, this tool will use it natively without
    a contract change.

    Returns:
        JSON string with keys: total_results (volumes seen for fallback),
        entries (list of unique journals), powered_by, and a `note` field
        when the fallback is active.
    """
    # Attempt service=4 first (forward-looking).
    payload4 = {
        "service": 4,
        "material": params.material,
        "issn": params.issn,
        "publisher": params.publisher,
        "pubyearfrom": params.pubyearfrom,
        "pubyearto": params.pubyearto,
        "count": params.count,
    }
    try:
        xml_text = await _get(payload4)
        parsed = _parse_feed(xml_text, "article")  # schema TBD; use article shape provisionally
        return json.dumps(parsed, ensure_ascii=False, indent=2)
    except ValueError as exc:
        # Expected for now: ERR_004 means service=4 is unavailable.
        if "ERR_004" not in str(exc):
            return _format_error(exc)
    except Exception as exc:  # noqa: BLE001
        return _format_error(exc)

    # Fallback: service=2 with the same identifying fields.
    payload2 = {
        "service": 2,
        "material": params.material,
        "issn": params.issn,
        "pubyearfrom": params.pubyearfrom,
        "pubyearto": params.pubyearto,
        "count": params.count,
    }
    try:
        xml_text = await _get(payload2)
        parsed = _parse_feed(xml_text, "volume")
        journals = _dedupe_journals(parsed["entries"])
        return json.dumps(
            {
                "total_results": parsed["total_results"],
                "items_per_page": parsed["items_per_page"],
                "entries": journals,
                "note": (
                    "service=4 (journal search) is documented but not yet "
                    "active; results derived from service=2 (volume search) "
                    "and deduplicated by journal."
                ),
                "powered_by": ATTRIBUTION,
            },
            ensure_ascii=False,
            indent=2,
        )
    except Exception as exc:  # noqa: BLE001
        return _format_error(exc)


@mcp.tool(
    name="jstage_get_article_by_doi",
    annotations={
        "title": "Look up a single J-STAGE article by DOI",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def jstage_get_article_by_doi(params: GetArticleByDoiInput) -> str:
    """Resolve a DOI to its J-STAGE article record.

    The J-STAGE WebAPI does not expose a DOI query parameter. This tool
    works in two stages:

    1. If the DOI matches J-STAGE's standard issuance pattern
       (10.<registrant>/<cdjournal>.<vol>.<no>_<page>), decompose it and
       query service=3 with cdjournal+vol, then return the entry whose
       <prism:doi> matches the requested DOI exactly.
    2. Otherwise, return the doi.org resolution URL with a note that
       the DOI is not in the J-STAGE-issued pattern and a direct API
       lookup is not possible.

    Returns:
        JSON string with the matching article record, or a degraded
        response with `resolution_url` and `note` for non-J-STAGE DOIs.
    """
    doi = _strip_doi_prefix(params.doi)
    match = JSTAGE_DOI_RE.match(doi)
    if not match:
        return json.dumps(
            {
                "doi": doi,
                "resolution_url": f"https://doi.org/{doi}",
                "note": (
                    "DOI does not match J-STAGE's standard pattern "
                    "(10.<registrant>/<cdjournal>.<vol>.<no>_<page>). "
                    "Direct API lookup is not possible; follow the "
                    "resolution_url to view the article on J-STAGE."
                ),
                "powered_by": ATTRIBUTION,
            },
            indent=2,
        )

    cdjournal = match.group("cdjournal")
    vol = match.group("vol")
    try:
        xml_text = await _get(
            {"service": 3, "cdjournal": cdjournal, "vol": vol, "count": 100}
        )
        parsed = _parse_feed(xml_text, "article")
    except Exception as exc:  # noqa: BLE001
        return _format_error(exc)

    for entry in parsed["entries"]:
        if (entry.get("doi") or "").strip() == doi:
            return json.dumps(
                {"entry": entry, "powered_by": ATTRIBUTION},
                ensure_ascii=False,
                indent=2,
            )

    return json.dumps(
        {
            "doi": doi,
            "resolution_url": f"https://doi.org/{doi}",
            "note": (
                f"Decomposed DOI to cdjournal='{cdjournal}', vol='{vol}', "
                "but no entry in that volume matched the DOI exactly. "
                "The DOI may use a non-standard suffix; follow the "
                "resolution_url to view it on J-STAGE."
            ),
            "powered_by": ATTRIBUTION,
        },
        indent=2,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()

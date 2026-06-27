"""J-STAGE MCP server.

A FastMCP stdio server exposing the J-STAGE WebAPI
(https://api.jstage.jst.go.jp/searchapi/do) for searching Japanese
academic articles and journals.

v2.0.0 — clean replacement of the response format. The record-retrieval tools
(jstage_search_articles, jstage_get_article_by_doi) now emit the unified
response envelope shared with cinii-mcp (see mediation.py / response-schema.json):
typed query/script, matching_mode, graduated breadth, per-item matched_in, typed
diagnostics, a loggable receipt, and the JST attribution. The navigation tools
(jstage_list_issues, jstage_search_journals) return structural JSON; they are not
literature retrieval and are out of envelope scope.

This is a breaking change from v1.x. J-STAGE attribution requirement: every
response carries the JST acknowledgment.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, Optional
from xml.etree import ElementTree as ET

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, field_validator

import mediation as M

__version__ = "2.0.3"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

API_BASE = "https://api.jstage.jst.go.jp/searchapi/do"
USER_AGENT = "jstage-mcp/2.0 (research; +https://www.jstage.jst.go.jp)"
DEFAULT_TIMEOUT = 30.0
MIN_REQUEST_INTERVAL = 1.0  # seconds — JST forbids bulk downloads
ATTRIBUTION = "Powered by J-STAGE (https://www.jstage.jst.go.jp/)"
MATCHING_MODE = "full_text_broad"
COVERAGE_NOTE = (
    "J-STAGE coverage reflects which learned societies deposit full text; "
    "absence here is not absence in the field."
)

STATUS_HINTS = {
    "WARN_002": (
        "J-STAGE judged the query too broad to return a full result set. Add a "
        "more specific term (a journal, author, or second keyword) to narrow it. "
        "A truncated or empty result here does not mean the literature is absent."
    ),
    "ERR_001": (
        "J-STAGE returned no usable result for this query. The term may be "
        "unmatched as written; try an alternative rendering, a component term, "
        "or a broader keyword before concluding the literature is absent."
    ),
}

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "prism": "http://prismstandard.org/namespaces/basic/2.0/",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}

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
    block = parent.find(f"atom:{tag}", NS)
    if block is None:
        return {"en": None, "ja": None}
    return {"en": _text(block.find("atom:en", NS)), "ja": _text(block.find("atom:ja", NS))}


def _bilingual_link(parent: ET.Element, tag: str) -> dict[str, Optional[str]]:
    block = parent.find(f"atom:{tag}", NS)
    if block is None:
        return {"en": None, "ja": None}
    return {"en": _text(block.find("atom:en", NS)), "ja": _text(block.find("atom:ja", NS))}


def _authors(entry: ET.Element) -> list[dict[str, Optional[str]]]:
    authors: list[dict[str, Optional[str]]] = []
    for author in entry.findall("atom:author", NS):
        en_block = author.find("atom:en", NS)
        ja_block = author.find("atom:ja", NS)
        en_names = [_text(n) for n in en_block.findall("atom:name", NS)] if en_block is not None else []
        ja_names = [_text(n) for n in ja_block.findall("atom:name", NS)] if ja_block is not None else []
        n = max(len(en_names), len(ja_names), 1)
        for i in range(n):
            authors.append(
                {
                    "ja": ja_names[i] if i < len(ja_names) else None,
                    "en": en_names[i] if i < len(en_names) else None,
                }
            )
    return [a for a in authors if a["en"] or a["ja"]]


def _check_status(root: ET.Element) -> Optional[dict[str, Any]]:
    """Return None on success; a warning dict for WARN_*; raise ValueError on error."""
    result = root.find("atom:result", NS)
    if result is None:
        return None
    status = _text(result.find("atom:status", NS))
    message = _text(result.find("atom:message", NS))
    if not status or status == "0":
        return None
    hint = STATUS_HINTS.get(status)
    if status.startswith("WARN"):
        return {"code": status, "message": message, "hint": hint}
    msg = message if (message and message != status) else "(no message)"
    detail = f"J-STAGE API {status}: {msg}"
    if hint:
        detail += f" — {hint}"
    raise ValueError(f"{status}|{detail}")


def _meta(root: ET.Element) -> dict[str, Any]:
    return {
        "total": int(_text(root.find("opensearch:totalResults", NS)) or 0),
        "start": int(_text(root.find("opensearch:startIndex", NS)) or 1) or 1,
    }


def _entry_to_item(entry: ET.Element, matched_in: str) -> dict[str, Any]:
    title = _bilingual(entry, "article_title")
    url = _bilingual_link(entry, "article_link")
    journal = _bilingual(entry, "material_title")
    ps = _text(entry.find("prism:startingPage", NS))
    pe = _text(entry.find("prism:endingPage", NS))
    pages = f"{ps}-{pe}" if ps and pe else (ps or None)
    pubyear = _text(entry.find("atom:pubyear", NS))
    year = int(pubyear) if pubyear and pubyear.isdigit() else None
    return M.make_item(
        title_ja=title["ja"],
        title_en=title["en"],
        authors=_authors(entry),
        journal_ja=journal["ja"],
        journal_en=journal["en"],
        volume=_text(entry.find("prism:volume", NS)),
        issue=_text(entry.find("prism:number", NS)),
        pages=pages,
        year=year,
        doi=_text(entry.find("prism:doi", NS)),
        url_ja=url["ja"],
        url_en=url["en"],
        matched_in=matched_in,
        record_type="article",
    )


def _parse_articles(xml_text: str, matched_in: str) -> tuple[dict[str, Any], list[dict], Optional[dict]]:
    root = ET.fromstring(xml_text)
    warning = _check_status(root)  # raises on hard error
    meta = _meta(root)
    items = [_entry_to_item(e, matched_in) for e in root.findall("atom:entry", NS)]
    # strip the single empty <entry/> the API returns on zero hits
    items = [it for it in items if it["title"]["ja"] or it["title"]["en"] or it["ids"]["doi"]]
    return meta, items, warning


# ---------------------------------------------------------------------------
# Field resolution + diagnostics
# ---------------------------------------------------------------------------

# (param name, matched_in role) in priority order
_FIELD_ROLES = [
    ("text", "fulltext"),
    ("article", "title"),
    ("abst", "abstract"),
    ("keyword", "metadata"),
    ("author", "metadata"),
    ("affil", "metadata"),
    ("material", "metadata"),
]


def _resolve_fields(params: "SearchArticlesInput") -> tuple[str, str]:
    """Return (normalized_query_string, matched_in) from the populated fields."""
    present = [(name, role, getattr(params, name)) for name, role in _FIELD_ROLES if getattr(params, name)]
    if not present:
        return "", "metadata"
    normalized = " ".join(v for _, _, v in present)
    matched_in = "fulltext" if any(name == "text" for name, _, _ in present) else present[0][1]
    return normalized, matched_in


def _diagnostics(
    *, total: int, breadth: str, script: str, api_warning: Optional[dict], api_error: Optional[dict]
) -> list[dict]:
    ds: list[dict] = []
    if api_error:
        ds.append(api_error)
    if script == "latin":
        ds.append(
            M.diag(
                "warning",
                "SCRIPT_LATIN_QUERY",
                f"Query is Latin-script; this matched romanized/English metadata only "
                f"({total} records). The Japanese-script form reaches a different, larger corpus.",
                "Re-issue in kanji/kana (e.g. 暴走族) to search the Japanese-language literature.",
            )
        )
    broad = bool(api_warning) or (not api_error and breadth in ("broad", "very_broad"))
    if broad:
        hint = (api_warning.get("hint") if api_warning else None) or (
            "Read the count as noisy, not as the size of the literature; relevant records "
            "may sit below the top. Narrow with a second term or inspect matched_in."
        )
        ds.append(
            M.diag(
                "warning",
                "BROAD_FULLTEXT",
                f"{total} records matched on full text; multi-word terms are matched loosely, "
                f"so most results may be only incidentally related.",
                hint,
            )
        )
    if total == 0 and not api_error and not api_warning:
        ds.append(
            M.diag(
                "warning",
                "LITERAL_COMPOUND_EMPTY",
                "No records for this rendering.",
                "Try an emic or component term, or an alternative Japanese rendering, "
                "before concluding the literature is absent.",
            )
        )
    if not ds:
        ds.append(M.diag("info", "OK", f"{total} record(s) on this match.", None))
    return ds


def _error_diag(exc: Exception) -> dict:
    if isinstance(exc, httpx.HTTPStatusError):
        return M.diag("error", "TRANSPORT_ERROR", f"J-STAGE returned HTTP {exc.response.status_code}.", "Retry shortly.")
    if isinstance(exc, httpx.TimeoutException):
        return M.diag("error", "TRANSPORT_ERROR", "Request to J-STAGE timed out.", "Retry shortly.")
    if isinstance(exc, httpx.HTTPError):
        return M.diag("error", "TRANSPORT_ERROR", f"Network error reaching J-STAGE: {exc}.", "Retry shortly.")
    if isinstance(exc, ValueError):
        code, _, detail = str(exc).partition("|")
        if code == "ERR_001":
            return M.diag("warning", "LITERAL_COMPOUND_EMPTY", "No records for this rendering.", STATUS_HINTS.get("ERR_001"))
        return M.diag("error", "API_ERROR", detail or str(exc), None)
    return M.diag("error", "API_ERROR", f"{type(exc).__name__}: {exc}", None)


# ---------------------------------------------------------------------------
# Pydantic input models
# ---------------------------------------------------------------------------


class _Base(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")


class SearchArticlesInput(_Base):
    text: Optional[str] = Field(default=None, description="Full-text keyword (title, abstract, body), Japanese or English.")
    article: Optional[str] = Field(default=None, description="Article title (substring).")
    author: Optional[str] = Field(default=None, description="Author name, Japanese or romanized.")
    affil: Optional[str] = Field(default=None, description="Author affiliation.")
    keyword: Optional[str] = Field(default=None, description="Author-supplied keywords.")
    abst: Optional[str] = Field(default=None, description="Abstract field only.")
    material: Optional[str] = Field(default=None, description="Journal (material) title.")
    issn: Optional[str] = Field(default=None, description="Journal ISSN (with or without hyphen).")
    cdjournal: Optional[str] = Field(default=None, description="J-STAGE journal code (e.g. 'istd').")
    vol: Optional[str] = Field(default=None, description="Volume filter.")
    no: Optional[str] = Field(default=None, description="Issue filter.")
    pubyearfrom: Optional[int] = Field(default=None, ge=1900, le=2100, description="Earliest year.")
    pubyearto: Optional[int] = Field(default=None, ge=1900, le=2100, description="Latest year.")
    count: int = Field(default=20, ge=1, le=100, description="Results per page (1–100).")
    start: int = Field(default=1, ge=1, description="1-indexed start position.")

    @field_validator("text", "article", "author", "affil", "keyword", "abst", "material")
    @classmethod
    def _non_empty(cls, v: Optional[str]) -> Optional[str]:
        return v if (v and v.strip()) else None


class ListIssuesInput(_Base):
    material: Optional[str] = Field(default=None)
    issn: Optional[str] = Field(default=None)
    cdjournal: Optional[str] = Field(default=None)
    pubyearfrom: Optional[int] = Field(default=None, ge=1900, le=2100)
    pubyearto: Optional[int] = Field(default=None, ge=1900, le=2100)
    count: int = Field(default=20, ge=1, le=100)
    start: int = Field(default=1, ge=1)


class GetArticleByDoiInput(_Base):
    doi: str = Field(..., description="DOI, with or without doi.org prefix.", min_length=5)


# ---------------------------------------------------------------------------
# Server + tools
# ---------------------------------------------------------------------------

mcp = FastMCP("jstage_mcp")


@mcp.tool(
    name="jstage_search_articles",
    annotations={"title": "Search J-STAGE articles", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def jstage_search_articles(params: SearchArticlesInput) -> str:
    """Search articles on J-STAGE. Returns the unified response envelope.

    J-STAGE matches `text` against full text and treats multi-word terms
    loosely, so a high `result.total` is often noisy — read `matching_mode`
    (full_text_broad), `result.breadth`, and the `diagnostics` before treating
    a count as the size of a literature. A `SCRIPT_LATIN_QUERY` diagnostic means
    the query searched romanized metadata only; re-issue in kanji/kana. The same
    string can return very different totals on CiNii (metadata conjunction).
    """
    normalized, matched_in = _resolve_fields(params)
    api_params = params.model_dump(exclude_none=True)
    api_params["service"] = 3
    issued = {k: v for k, v in api_params.items() if k != "service"}
    script = M.detect_script(normalized)

    try:
        xml_text = await _get(api_params)
        meta, items, warning = _parse_articles(xml_text, matched_in)
        total, start = meta["total"], meta["start"]
        api_error = None
    except Exception as exc:  # noqa: BLE001
        items, warning, total, start = [], None, 0, params.start
        api_error = _error_diag(exc)

    breadth = M.classify_breadth(total)
    diags = _diagnostics(total=total, breadth=breadth, script=script, api_warning=warning, api_error=api_error)
    coverage = COVERAGE_NOTE if (total == 0 or breadth == "narrow") else None

    env = M.build_envelope(
        server="jstage",
        operation="search_articles",
        input_terms=normalized,
        normalized=normalized,
        params=issued,
        matching_mode=MATCHING_MODE,
        total=total,
        start=start,
        items=items,
        diagnostics=diags,
        attribution=ATTRIBUTION,
        coverage_note=coverage,
    )
    return M.dumps(env)


@mcp.tool(
    name="jstage_get_article_by_doi",
    annotations={"title": "Look up a J-STAGE article by DOI", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def jstage_get_article_by_doi(params: GetArticleByDoiInput) -> str:
    """Resolve a J-STAGE DOI to its article record. Returns the unified envelope
    (operation 'resolve_doi') with one item on success, or zero items plus a
    diagnostic when the DOI is not in J-STAGE's issuance pattern or is unmatched.
    """
    doi = params.doi.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:", "DOI:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix):]
            break
    issued = {"doi": doi}
    match = JSTAGE_DOI_RE.match(doi)

    if not match:
        env = M.build_envelope(
            server="jstage", operation="resolve_doi", input_terms=doi, normalized=doi,
            params=issued, matching_mode=MATCHING_MODE, total=0, start=1, items=[],
            diagnostics=[M.diag("warning", "LITERAL_COMPOUND_EMPTY",
                "DOI is not in J-STAGE's issuance pattern (10.<registrant>/<cdjournal>.<vol>.<no>_<page>); "
                "a direct API lookup is not possible.",
                f"Resolve via https://doi.org/{doi}.")],
            attribution=ATTRIBUTION,
        )
        return M.dumps(env)

    try:
        xml_text = await _get({"service": 3, "cdjournal": match.group("cdjournal"), "vol": match.group("vol"), "count": 100})
        _meta_, items, _warn = _parse_articles(xml_text, "metadata")
        api_error = None
    except Exception as exc:  # noqa: BLE001
        items, api_error = [], _error_diag(exc)

    hit = [it for it in items if (it["ids"]["doi"] or "").strip() == doi]
    if hit:
        diags = [M.diag("info", "OK", "Resolved to one article record.", None)]
        env_items, total = hit[:1], 1
    elif api_error:
        diags, env_items, total = [api_error], [], 0
    else:
        diags = [M.diag("warning", "LITERAL_COMPOUND_EMPTY",
            f"Decomposed the DOI to cdjournal='{match.group('cdjournal')}', vol='{match.group('vol')}', "
            "but no entry matched exactly.", f"Resolve via https://doi.org/{doi}.")]
        env_items, total = [], 0

    env = M.build_envelope(
        server="jstage", operation="resolve_doi", input_terms=doi, normalized=doi,
        params=issued, matching_mode=MATCHING_MODE, total=total, start=1,
        items=env_items, diagnostics=diags, attribution=ATTRIBUTION,
    )
    return M.dumps(env)


# --- Navigation tools (structural JSON; out of envelope scope) --------------


@mcp.tool(
    name="jstage_list_issues",
    annotations={"title": "List volumes & issues of a J-STAGE journal", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def jstage_list_issues(params: ListIssuesInput) -> str:
    """Return the volume/issue spine of a journal (by material/issn/cdjournal).

    Navigation aid, not literature retrieval: returns structural JSON (volumes
    with publisher/journal metadata), not the record envelope.
    """
    api_params = params.model_dump(exclude_none=True)
    api_params["service"] = 2
    try:
        xml_text = await _get(api_params)
        root = ET.fromstring(xml_text)
        warning = _check_status(root)
        meta = _meta(root)
        entries = root.findall("atom:entry", NS)
        cap = min(params.count, 20)  # hard ceiling: a journal can list hundreds of volumes
        vols = []
        for entry in entries[:cap]:
            jt = _bilingual(entry, "material_title")
            vols.append({
                "label": _bilingual(entry, "vols_title"),
                "url": _bilingual_link(entry, "vols_link"),
                "journal": {"title": jt, "cdjournal": _text(entry.find("atom:cdjournal", NS)),
                            "issn": _text(entry.find("prism:issn", NS)), "eissn": _text(entry.find("prism:eIssn", NS))},
                "volume": _text(entry.find("prism:volume", NS)),
                "pubyear": _text(entry.find("atom:pubyear", NS)),
            })
        out = {"total_results": meta["total"], "returned": len(vols),
               "truncated": len(entries) > len(vols),
               "volumes": vols, "powered_by": ATTRIBUTION,
               "query": {k: v for k, v in api_params.items() if k != "service"}}
        if warning:
            out["warning"] = warning["code"]
            out["hint"] = warning.get("hint")
        return json.dumps(out, ensure_ascii=False, indent=2)
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": str(exc), "powered_by": ATTRIBUTION}, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    mcp.run()

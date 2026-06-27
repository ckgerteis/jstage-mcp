# jstage-mcp

A FastMCP stdio server exposing the [J-STAGE WebAPI](https://www.jstage.jst.go.jp/static/pages/JstageServices/TAB3/-char/en) as three tools for use with Claude Desktop.

> **v2 is a breaking change.** The record-retrieval tools now return one
> structured JSON *response envelope* (shared with
> [cinii-mcp](https://github.com/ckgerteis/cinii-mcp)) instead of v1's ad-hoc
> JSON. The envelope moves the interpretation keys — how a query was matched,
> how broad the result is, what script was searched — into typed fields. See
> **Response format** below. v2 also ships a companion `mediation.py` that must
> sit beside `server.py`, and retires `jstage_search_journals` (see *Limitations*).

## Tools

| Tool | Purpose | Returns |
| --- | --- | --- |
| `jstage_search_articles` | Full-text / author / title / journal search across J-STAGE articles | response envelope |
| `jstage_get_article_by_doi` | Resolve a J-STAGE DOI to its article record | response envelope |
| `jstage_list_issues` | Volume & issue spine for a known title, ISSN, or `cdjournal` | structural JSON (navigation) |

The two record-retrieval tools emit the unified envelope below.
`jstage_list_issues` is a navigation aid and returns a bounded structural list
(`total_results`, `returned`, `truncated`, `volumes`), not the envelope. Every
response preserves the JST attribution.

## Response format

`jstage_search_articles` and `jstage_get_article_by_doi` return:

```jsonc
{
  "server": "jstage",
  "operation": "search_articles",
  "query": { "input_terms": "...", "normalized": "...",
             "script": "han|kana|han_kana|latin|mixed", "params": { ... } },
  "matching_mode": "full_text_broad",        // J-STAGE matches full text, loosely
  "result": { "total": 0, "returned": 0, "start": 1,
              "breadth": "none|narrow|broad|very_broad" },
  "items": [ { "title": {"ja":..,"en":..,"romanized":..},
               "authors": [{"ja":..,"en":..}],
               "source": {"journal_ja":..,"journal_en":..,"volume":..,"issue":..,"pages":..,"year":..},
               "ids": {"doi":..,"crid":..,"naid":..,"url_ja":..,"url_en":..},
               "matched_in": "fulltext|metadata", "record_type": "article" } ],
  "diagnostics": [ { "level": "info|warning|error", "code": "...", "message": "...", "hint": "..." } ],
  "coverage_note": "...|null",
  "receipt": { "issued_at": "<ISO-8601>", "query_hash": "sha256:...", "result_ids": [ ... ] },
  "attribution": "Powered by J-STAGE (https://www.jstage.jst.go.jp/)"
}
```

Diagnostic codes: `OK`, `BROAD_FULLTEXT` (a loose full-text match returned a large,
likely-noisy set — read the count as noisy, not as the size of a literature),
`SCRIPT_LATIN_QUERY` (a romaji query matched romanized metadata only; re-issue in
kanji/kana), `LITERAL_COMPOUND_EMPTY` (no usable result for this rendering),
`API_ERROR`, `TRANSPORT_ERROR`. The `receipt` is designed to be logged so a
search can be reconstructed.

## Install (Windows, alongside CiNii / OpenAlex / Semantic Scholar)

The server is `server.py` plus a companion `mediation.py` (the shared response
envelope; pure standard library, no extra dependency). **Both files must live in
the same directory.** Use a dedicated virtual environment so it doesn't collide
with other MCP stacks.

```powershell
# from the directory containing server.py and mediation.py
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -e .
```

Verify the server boots:

```powershell
.venv\Scripts\python.exe server.py --help
```

## Claude Desktop configuration

Add an entry to `%APPDATA%\Claude\claude_desktop_config.json` under `mcpServers`. Adjust the absolute paths to match your install location.

```json
{
  "mcpServers": {
    "jstage": {
      "command": "C:\\path\\to\\jstage-mcp\\.venv\\Scripts\\python.exe",
      "args": ["C:\\path\\to\\jstage-mcp\\server.py"]
    }
  }
}
```

Restart Claude Desktop. The three tools should appear under "jstage" in the tool list.

## Rate limiting

The server enforces a one-second minimum interval between outbound requests in line with JST's prohibition on bulk downloads. The limit is per-process; if you run multiple Claude Desktop sessions concurrently you may exceed it, so don't.

## Limitations

- **`jstage_search_journals` is retired in v2.** It was a fallback for the
  journal-search endpoint (`service=4`) that J-STAGE announced on 26 March 2026
  but the public API still rejects with `ERR_004`. Rather than ship an envelope
  around a stub, the tool is deferred; it will return when `service=4` is live.
- **`jstage_list_issues` is bounded.** A long-running journal can list hundreds
  of volumes; the tool caps the returned list (`returned`, `truncated`,
  `total_results`) to avoid oversized responses.
- **`jstage_get_article_by_doi` requires J-STAGE-issued DOIs.** The WebAPI does not expose a `doi=` query parameter. The tool decomposes DOIs that follow J-STAGE's pattern (`10.<registrant>/<cdjournal>.<vol>.<no>_<page>`) into `cdjournal+vol` and matches the result against the response. For DOIs outside that pattern it reports `LITERAL_COMPOUND_EMPTY` with the doi.org resolution URL.
- **Commercial use requires registration.** Per the JST Terms of Use, commercial use needs an application form sent to `contact@jstage.jst.go.jp`. Research and teaching use does not.

## API notes

Endpoint: `https://api.jstage.jst.go.jp/searchapi/do`

Service codes used:
- `service=2` — Volumes/issues (`jstage_list_issues`)
- `service=3` — Article search (`jstage_search_articles`, `jstage_get_article_by_doi`)
- `service=4` — Journal search (documented, not yet live; see *Limitations*)

Valid article-search query parameters confirmed against the live API:
`material, article, author, affil, keyword, abst, text, issn, cdjournal, vol, no, pubyearfrom, pubyearto, start, count`.

## Attribution

> Powered by [J-STAGE](https://www.jstage.jst.go.jp/)

This string is included in every tool response.

## Citation

If this software supports your research, please cite it. See [`CITATION.cff`](CITATION.cff), or use the "Cite this repository" button on GitHub.

## License

[MIT](LICENSE) © 2026 Christopher Gerteis.

This license covers the server code only. It grants no rights over J-STAGE content or the J-STAGE WebAPI, which remain governed by JST's [Terms of Use](https://www.jstage.jst.go.jp/static/pages/WebAPI/-char/ja).

## Disclaimer

A research tool, maintained on a best-effort basis and provided "as is", without warranty. Not affiliated with or endorsed by the Japan Science and Technology Agency. JST does not provide support for the WebAPI.

## Author

[Dr Christopher Gerteis](https://www.christophergerteis.net), SOAS University of London.

# jstage-mcp

A FastMCP stdio server exposing the [J-STAGE WebAPI](https://www.jstage.jst.go.jp/static/pages/JstageServices/TAB3/-char/en) as four tools for use with Claude Desktop.

## Tools

| Tool | Purpose |
| --- | --- |
| `jstage_search_articles` | Full-text / author / title / journal search across J-STAGE articles |
| `jstage_list_issues` | Volume & issue spine for a known title, ISSN, or `cdjournal` |
| `jstage_search_journals` | Find journals by title / ISSN / publisher (see *Limitations*) |
| `jstage_get_article_by_doi` | Resolve a J-STAGE DOI to its full article record |

All tools return one typed JSON response envelope with bilingual (English / Japanese) titles, authors, and journal names where J-STAGE provides them — see [Response format](#response-format) below. The JST attribution requirement is met by the envelope's `attribution` field, present in every response.

## Response format

Every tool returns one JSON response envelope, built by `mediation.py` and defined in [`response-schema.json`](response-schema.json). Schema version 2.3.0. The same module and schema are vendored byte-identically across the server family, so an envelope from one server can be read by a consumer written for another.

The envelope reports how the search was made, not only what it found:

- **`searched_for`** — on search operations, the term actually sent, its detected script, and the matching mode, hoisted to the top of the envelope so a relaying client cannot drop it. Fetch operations (`jstage_get_article_by_doi`, `jstage_list_issues`) omit it: they were handed an identifier and chose no term.
- **`query`** — `input_terms` as supplied, `normalized` as sent, and the detected `script`. This pair is the record of any rendering performed between the caller's language and the corpus.
- **`matching_mode`** — `full_text_broad` for this server. It tells you how to read `result.total`.
- **`result.breadth`** — `none`, `narrow` (1–50), `broad` (51–1000), `very_broad` (>1000). Thresholds are low on purpose: a few hundred hits that look like a literature are marked rather than passed through clean.
- **`items[].matched_in`** — which field the match was made in, per record.
- **`receipt`** — an ISO 8601 timestamp, a SHA-256 taken over the normalised query and its parameters, and the identifiers returned. The hash verifies a term you already hold; it cannot be inverted to produce one, so the unit of deposit is the envelope, not the receipt.
- **`attribution`** — the required credit line, in every response.

### Diagnostic codes

Typed and closed. A diagnostic is never prose the client has to parse.

| Code | Level | Meaning |
| --- | --- | --- |
| `OK` | info | Records returned; nothing to flag. |
| `BROAD_FULLTEXT` | warning | The match was made on full text, where multi-word terms are matched loosely, so a high `result.total` is often noisy. |
| `SCRIPT_LATIN_QUERY` | warning | The query was Latin-script, so it matched romanised and English metadata only. Re-issue in kanji or kana. |
| `LITERAL_COMPOUND_EMPTY` | warning | No records for this rendering. Try an emic or component term, or an alternative Japanese rendering. |
| `API_ERROR` | error | The API answered, and answered with an error. |
| `TRANSPORT_ERROR` | error | The request did not complete. Kept distinct from `API_ERROR` because a failed search has an unknown result and must never be written up as an absence. |
| `RECEIPT_NOT_DEPOSITED` | info | The response was not written to the query ledger, because `MCP_RECEIPT_LOG` is unset. The search is unaffected; no receipt survives it. |
| `RECEIPT_WRITE_FAILED` | warning | `MCP_RECEIPT_LOG` is set, the write was attempted, and it did not land. Distinct from the line above because one is a choice and the other is a fault. |

### Query receipts

Every envelope can be deposited to an append-only, hash-chained JSONL log by `ledger.py`. It is **off unless `MCP_RECEIPT_LOG` is set**, and a logging failure is swallowed rather than raised — a search matters more than the record of it. Secrets are redacted before a line is composed.

Since schema 2.3.0 the envelope says so. When a response is not deposited, `emit()` appends `RECEIPT_NOT_DEPOSITED` if the variable is unset, or `RECEIPT_WRITE_FAILED` if it is set and the write did not land. The gap is then visible in the artefact that becomes the record, rather than only in a configuration file. `mediation.deposit_enabled()` reports the same fact on demand.

```
MCP_RECEIPT_LOG=C:\path\to\receipts.jsonl
MCP_RECEIPT_SESSION=project-or-article-slug
MCP_RECEIPT_STRICT=1        # optional: make logging failure raise
```

Verify a deposited log's hash chain:

```bash
python ledger.py verify receipts.jsonl
```

## Install (Windows, alongside CiNii / OpenAlex / Semantic Scholar)

The server is single-file and has only three runtime dependencies. Use a dedicated virtual environment so it doesn't collide with other MCP stacks.

```powershell
# from the directory containing server.py
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

Restart Claude Desktop. The four tools should appear under "jstage" in the tool list.

## Rate limiting

The server enforces a one-second minimum interval between outbound requests in line with JST's prohibition on bulk downloads. The limit is per-process; if you run multiple Claude Desktop sessions concurrently you may exceed it, so don't.

## Limitations

- **`jstage_search_journals` runs against a fallback.** J-STAGE announced a journal-search endpoint (`service=4`) on 26 March 2026, but the public API currently rejects that service code with `ERR_004`. The tool probes `service=4` first and, on failure, falls back to `service=2` (volume search) with results deduplicated by journal. When JST activates `service=4`, the tool will use it natively without a contract change.
- **`jstage_get_article_by_doi` requires J-STAGE-issued DOIs.** The WebAPI does not expose a `doi=` query parameter. The tool decomposes DOIs that follow J-STAGE's pattern (`10.<registrant>/<cdjournal>.<vol>.<no>_<page>`) into `cdjournal+vol` and matches the result against the response. For DOIs outside that pattern the tool returns the doi.org resolution URL with a note.
- **Commercial use requires registration.** Per the JST Terms of Use, commercial use needs an application form sent to `contact@jstage.jst.go.jp`. Research and teaching use does not.

## API notes

Endpoint: `https://api.jstage.jst.go.jp/searchapi/do`

Service codes used:
- `service=2` — Volumes/issues
- `service=3` — Article search
- `service=4` — Journal search (documented, not yet live)

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

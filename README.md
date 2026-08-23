# jstage-mcp

A FastMCP stdio server exposing the [J-STAGE WebAPI](https://www.jstage.jst.go.jp/static/pages/JstageServices/TAB3/-char/en) as three tools for use with Claude Desktop.

## What this is for

J-STAGE holds the full text of journals published by Japanese learned societies, and this searches inside the articles rather than across a catalogue. A term that no cataloguer chose as a keyword is still findable if an author used it in an argument, which makes this the route for concepts that circulate before they are named.

Resolve a J-STAGE DOI straight to its record, or walk a journal's volume and issue spine to see a run whole.

Run a term here and on [`cinii-mcp`](https://github.com/ckgerteis/cinii-mcp) and read the gap: a wide divergence tells you whether your vocabulary belongs to catalogue description or to the prose of the field, which is a finding about the literature before it is a finding in it.

## Tools

| Tool | Purpose |
| --- | --- |
| `jstage_search_articles` | Full-text / author / title / journal search across J-STAGE articles |
| `jstage_list_issues` | Volume & issue spine for a known title, ISSN, or `cdjournal` |
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
| `RECEIPT_NOT_DEPOSITED` | info | The response was not written to the query ledger, because no receipts destination is configured. The search is unaffected; no receipt survives it. |
| `RECEIPT_WRITE_FAILED` | warning | A receipts destination is set, the write was attempted, and it did not land. Distinct from the line above because one is a choice and the other is a fault. |

### Query receipts

Every envelope can be deposited to an append-only, hash-chained JSONL log by `ledger.py`. It is **off unless `MCP_RECEIPT_DIR` (or the legacy `MCP_RECEIPT_LOG`) is set**, and a logging failure is swallowed rather than raised — a search matters more than the record of it. Secrets are redacted before a line is composed.

Since schema 2.3.0 the envelope says so. When a response is not deposited, `emit()` appends `RECEIPT_NOT_DEPOSITED` if the variable is unset, or `RECEIPT_WRITE_FAILED` if it is set and the write did not land. The gap is then visible in the artefact that becomes the record, rather than only in a configuration file. `mediation.deposit_enabled()` reports the same fact on demand.

```
MCP_RECEIPT_DIR=C:\path\to\receipts        # a folder, not a file
MCP_RECEIPT_SESSION=project-or-article-slug
MCP_RECEIPT_STRICT=1                         # optional: make logging failure raise
MCP_RECEIPT_LOG=C:\path\to\receipts.jsonl  # legacy single file; ignored when _DIR is set
```

**A folder, and one file per server.** `MCP_RECEIPT_DIR` points at a directory
and each server writes its own `<server>.jsonl` inside it. That is not tidiness.
Appending is read-the-last-hash-then-write, and the lock around it is a threading
lock, which holds within one process and not between several — six servers are
six processes, and two answering at the same moment will both read the same
predecessor and both claim it. Measured, not theorised: six processes writing 150
lines to one file produced fourteen forks. `MCP_RECEIPT_LOG` still works and is
still correct for a single server; it is the wrong shape for a family.

`install.ps1` sets this up for all six and writes a README into the folder.

Verify one chain, or the whole folder:

```bash
jstage-mcp-ledger verify      receipts/jstage.jsonl
jstage-mcp-ledger verify-dir  receipts
jstage-mcp-ledger manifest    receipts        # writes receipts/manifest.json
```

`verify` exits non-zero on failure and says which kind it found: a **fork**
(concurrent writers — a configuration fault, and every line is still there), a
**missing** line, a **reordering**, or **tamper** (a line that does not hash to
its own content). Only the last is a claim about honesty, and reporting them
alike would invite a reader to mistake one for the other. The manifest is the
object to cite: one description of the whole deposit — per-file line counts,
first and last timestamps, terminal hashes, and combined totals by server,
script and session.

## Install

The package installs a `jstage-mcp` console script. It is namespaced, so it can
share one environment with the rest of this server family.

```bash
python3 -m venv .venv
.venv/bin/pip install .
```

On Windows:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\pip.exe install .
```

Or straight from the repository, without cloning:

```bash
uvx --from "git+https://github.com/ckgerteis/jstage-mcp" jstage-mcp
```

Verify the install:

```bash
.venv/bin/python -c "import jstage_mcp; print(jstage_mcp.__version__)"
```

That fails loudly if the package or one of its vendored modules is missing. Do
not use `jstage-mcp --help` as the check: unknown arguments are ignored, the
server starts, reads end-of-input and exits 0, so it reports success whatever
the state of the code.

### The whole family at once

`install.ps1` — vendored byte-identical into all six repositories — installs any
or all of `cinii`, `jstage`, `ndl`, `korea_scholarship`, `openalex` and
`semantic_scholar` into one environment, asks once for a receipts folder, and
registers them all against it.

```powershell
.\install.ps1                                   # all six
.\install.ps1 -Servers jstage -ReceiptsDir "D:\research\receipts"
```

It reads a sibling checkout where one exists and fetches the rest from GitHub,
carries across any credentials already registered rather than asking again, and
stops rather than guessing if the servers already registered disagree about where
the receipts go.

## Claude Desktop configuration

Add an entry to `%APPDATA%\Claude\claude_desktop_config.json` under
`mcpServers`, pointing at the console script in the environment you installed
into. On macOS or Linux use the absolute path to `.venv/bin/jstage-mcp`.

```json
{
  "mcpServers": {
    "jstage": {
      "command": "C:\\path\\to\\.venv\\Scripts\\jstage-mcp.exe"
    }
  }
}
```

**Changed in 3.0.0.** Earlier versions were registered by path —
`"command": "…\\python.exe", "args": ["…\\server.py"]`. That entry will not
start this version, because `server.py` is now a module inside a package rather
than a script beside its imports. Replace it with the console script above.

Restart Claude Desktop. The three tools should appear under "jstage" in the
tool list.

## Rate limiting

The server enforces a one-second minimum interval between outbound requests in line with JST's prohibition on bulk downloads. The limit is per-process; if you run multiple Claude Desktop sessions concurrently you may exceed it, so don't.

## Limitations

- **There is no journal-search tool.** `jstage_search_journals` existed in v1.x and was removed in v2.0.0. J-STAGE announced a journal-search endpoint (`service=4`) on 26 March 2026 and the public API still rejects that service code with `ERR_004`; a tool that silently falls back to volume search is not a journal search, and this server would rather not offer one. Until JST activates `service=4`, use `jstage_list_issues` against a known title, ISSN or `cdjournal`.
- **`jstage_get_article_by_doi` requires J-STAGE-issued DOIs.** The WebAPI does not expose a `doi=` query parameter. The tool decomposes DOIs that follow J-STAGE's pattern (`10.<registrant>/<cdjournal>.<vol>.<no>_<page>`) into `cdjournal+vol` and matches the result against the response. For DOIs outside that pattern the tool returns the doi.org resolution URL with a note.
- **Commercial use requires registration.** Per the JST Terms of Use, commercial use needs an application form sent to `contact@jstage.jst.go.jp`. Research and teaching use does not.

## API notes

Endpoint: `https://api.jstage.jst.go.jp/searchapi/do`

Service codes used:
- `service=2` — Volumes/issues
- `service=3` — Article search
- `service=4` — Journal search (documented, rejected with `ERR_004` as of 23 August 2026; not used by any tool)

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

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

Three routes. All three give you the same server; pick by how much you want to see of it.

### One click: the Claude Desktop bundle

Download the `.mcpb` for your platform (Windows x64, Apple Silicon, Linux x64; Intel Macs use the pip route below) from the [latest release](https://github.com/ckgerteis/jstage-mcp/releases/latest) and open it; Claude Desktop installs it. Claude Desktop asks only for a receipts folder at install time. The bundle carries every library it needs, but not Python itself: a Python 3.10+ interpreter must be on the machine (`python` on Windows, `python3` on macOS and Linux).

### From GitHub, pinned to a release

```bash
pip install "git+https://github.com/ckgerteis/jstage-mcp@v3.0.0"
# or, without an environment of your own:
uvx --from "git+https://github.com/ckgerteis/jstage-mcp@v3.0.0" jstage-mcp
```

installs the `jstage-mcp` console script and `jstage-mcp-ledger`. The tag is the thing to cite; `@main` gets whatever is current. Then register it in Claude Desktop (below), or let `install.py` do that.

### The whole family

```bash
pip install "git+https://github.com/ckgerteis/bibliograph-mcp@v1.0.0" && bibliograph install
```

installs all six servers and registers them together — one receipts folder, credentials asked for once. See [bibliograph-mcp](https://github.com/ckgerteis/bibliograph-mcp). From a checkout of this repository, `python install.py` does the same for this server alone, `python install.py --all` for the six, on Windows, macOS and Linux; `install.ps1` remains for Windows.

### From source

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

### Installing more than this one

Six independent packages. None imports another, none depends on another, and
each installs and answers on its own — `pip install .` in this directory is a
complete install of this server and nothing else.

They do share three things: a response envelope, a query ledger, and — if you
run more than one — a receipts folder. `install.ps1` is vendored byte-identical
into all six and handles that on Windows; `install.py` is its cross-platform port. **Both install this server by default**, because
cloning one repository is not a request for five more.

```powershell
.\install.ps1                        # this server
.\install.ps1 -All                   # all six
.\install.ps1 -Servers jstage,cinii        # a chosen subset
```

Whatever subset you name is registered against one receipts folder, asked for
once. The script prefers a sibling checkout to the network, carries across
credentials already registered rather than asking again, leaves servers it was
not asked about alone, and stops rather than guessing where the servers already
registered disagree about the folder or the session slug. It also asserts that
`ledger.py` and `mediation.py` are byte-identical across everything it
installed, so two envelope versions cannot end up in one environment unnoticed.

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

## Tests

```bash
.venv/bin/python tests/smoke_stdio.py
```

Starts the installed console script over stdio, performs the MCP handshake, and checks `tools/list` against the tool table above; exits non-zero on a mismatch. `RUN_LIVE=1 … <tool> '<json params>'` adds one live call and reports the envelope's diagnostic codes.

## License

[MIT](LICENSE) © 2026 Christopher Gerteis.

This license covers the server code only. It grants no rights over J-STAGE content or the J-STAGE WebAPI, which remain governed by JST's [Terms of Use](https://www.jstage.jst.go.jp/static/pages/WebAPI/-char/ja).

## Disclaimer

A research tool, maintained on a best-effort basis and provided "as is", without warranty. Not affiliated with or endorsed by the Japan Science and Technology Agency. JST does not provide support for the WebAPI.

## Author

[Dr Christopher Gerteis](https://www.christophergerteis.net), SOAS University of London.

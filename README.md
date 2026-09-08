# jstage-mcp

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20999898.svg)](https://doi.org/10.5281/zenodo.20999898)

A FastMCP stdio server exposing the [J-STAGE WebAPI](https://www.jstage.jst.go.jp/static/pages/JstageServices/TAB3/-char/en) as three tools for use with Claude Desktop.

## What this is for

J-STAGE holds the full text of journals published by Japanese learned societies, and this searches inside the articles rather than across a catalogue. A term that no cataloguer chose as a keyword is still findable if an author used it in an argument, which makes this the route for concepts that circulate before they are named.

Resolve a J-STAGE DOI straight to its record, or walk a journal's volume and issue spine to see a run whole.

Run a term here and on [`cinii-mcp`](https://github.com/ckgerteis/cinii-mcp) and read the gap: a wide divergence tells you whether your vocabulary belongs to catalogue description or to the prose of the field, which is a finding about the literature before it is a finding in it.

## What the receipts are for

A search you cannot re-run is a claim you cannot check. When a footnote rests on a database
query, say that no article in this index uses a term before a certain year, the reader is asked to
take the search on trust: which term, in which script, on what date, against which index and which
version of it, and how far down the results the author went. Ordinary searching leaves none of
that behind. This server leaves all of it. Every
query-answering tool returns its envelope through the ledger, which appends one line to an
append-only file: the term actually sent and its script, how the source matched it, how many
records existed and how many came back, the diagnostics, the tool and its parameters, the server
version, a timestamp, and the hash of the previous line. The hash makes the file a chain: a line
cannot be altered, removed or reordered afterwards without the verifier saying so.

What that gives a researcher:

- **A citable search.** Name the receipt in the footnote (session slug, server, date, line hash)
  and a reader can see exactly what was asked and run it again against the same version.
- **Negative findings that carry weight.** "Not found" is evidence only if the search that
  produced it is on record, with its term, its script and its breadth.
- **A method section that writes itself.** `jstage-mcp-ledger` `manifest <folder>` summarises every
  query a project made, by server, script and session: the disclosure a journal, a
  data-availability statement or a research-integrity review asks for.
- **A record of AI-mediated research.** When a model chose the term, the receipt shows the term
  it chose and what came back, which is the thing to disclose about work done with an assistant.
- **Nothing interpreted.** The receipt is the source's own answer with credentials removed. The
  server does not summarise, rank or paraphrase, so the record is of the source, not of the tool.

Receipts are off until you name a folder (`MCP_RECEIPT_DIR`); each server then writes its own
`<server>.jsonl` inside it, and `MCP_RECEIPT_SESSION` stamps a project or article slug on every
line so one folder can serve several projects. `jstage-mcp-ledger` `verify-dir <folder>` checks the chains.
The mechanics, the variables and what the envelope says when nothing is deposited are in the
receipts section below.

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
| `SCRIPT_LATIN_QUERY` | warning | The query was Latin-script, so it matched Latin-script text and metadata only (English-language articles and romanised fields), not the Japanese-language corpus. Re-issue in kanji or kana. |
| `LITERAL_COMPOUND_EMPTY` | warning | No records for this rendering. Try an emic or component term, or an alternative Japanese rendering. |
| `API_ERROR` | error | The API answered, and answered with an error — including an HTTP error status. The result is unknown, not empty. |
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

**Python.** The pip and source routes need Python 3.10 or later; 3.10, 3.12, 3.13 and 3.14 are tested in CI on Windows, macOS and Linux. The Claude Desktop bundle uses whichever of these is already installed, and has uv download one only if none is.

### Getting Python

Every route needs Python 3.10 to 3.14. The Claude Desktop bundle uses one already on the machine
and has uv download one only if none is; the other routes also need the `venv` module, which the
official installers include.

- **Windows.** Download the 64-bit installer from [python.org/downloads](https://www.python.org/downloads/)
  and run it; tick "Add python.exe to PATH" on the first screen. Afterwards `py --version` (the
  launcher the installer adds) or `python --version` in a new terminal should print 3.1x. If typing
  `python` opens the Microsoft Store instead, Windows has no Python yet: that Store page is a stub,
  and it is also what "'python' is not recognized" usually means.
- **macOS.** The [python.org installer](https://www.python.org/downloads/macos/), or
  `brew install python@3.13` with [Homebrew](https://brew.sh). The `/usr/bin/python3` that Xcode's
  command-line tools provide may be older than 3.10; `python3 --version` says.
- **Linux.** Your distribution's package: `sudo apt install python3 python3-venv` on Debian and
  Ubuntu, `sudo dnf install python3` on Fedora. Or let uv provide one (next line).
- **Any platform, with uv.** [uv](https://docs.astral.sh/uv/getting-started/installation/)
  installs Python itself: `uv python install 3.13`, then `uv venv` or the `uvx` route below.

### One click: the Claude Desktop bundle

Download `jstage-mcp-3.1.1.mcpb` from the [latest release](https://github.com/ckgerteis/jstage-mcp/releases/latest) and open it; Claude Desktop installs it. One bundle serves Windows, macOS (Apple Silicon and Intel) and Linux. Claude Desktop asks only for a receipts folder at install time.

The bundle carries the server's source and a lock file, nothing compiled, and needs no Python of its own: Claude Desktop runs it with [uv](https://docs.astral.sh/uv/), using a uv already on your PATH if there is one and otherwise the copy the app ships. On first launch uv uses a Python 3.10 or later already on the machine, downloading one only if there is none, and installs the locked libraries: roughly 40 MB, or 60 MB with an interpreter, which took 26 to 46 seconds on the author's connection; later launches take under a second. If the first launch is slow enough that Claude Desktop reports the server disconnected, restart the app: what uv already fetched is cached, and the second launch completes. Bundles before 3.1.0 vendored libraries compiled for CPython 3.12 only and failed on every other interpreter; see [Troubleshooting](#troubleshooting).

### From GitHub, pinned to a release

```bash
pip install "git+https://github.com/ckgerteis/jstage-mcp@v3.1.1"
# or, without an environment of your own:
uvx --from "git+https://github.com/ckgerteis/jstage-mcp@v3.1.1" jstage-mcp
```

installs the `jstage-mcp` console script and `jstage-mcp-ledger`. The tag is the thing to cite; `@main` gets whatever is current. Then register it in Claude Desktop (below), or let `install.py` do that.

### The whole family

```bash
pip install "git+https://github.com/ckgerteis/bibliograph-mcp@v1.0.2" && bibliograph install
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

Nothing about where things go is decided for you. The script asks where to
install (the virtual environment Claude Desktop will be pointed at), which
folder receives the receipts, and which session slug to stamp on them,
offering a neutral suggestion for each that Enter accepts; run without a
terminal it does not guess, and stops unless `--venv` and `--receipts-dir`
(or `--no-receipts`; `-VenvDir` and `-ReceiptsDir` for `install.ps1`) say
so. Whatever subset you name is registered against one receipts folder, asked for
once. The script prefers a sibling checkout to the network, carries across
credentials already registered rather than asking again, leaves servers it was
not asked about alone, and stops rather than guessing where the servers already
registered disagree about the folder or the session slug. It also asserts that
`ledger.py` and `mediation.py` are byte-identical across everything it
installed, so two envelope versions cannot end up in one environment unnoticed.

### Any other MCP client

Nothing here is specific to Claude. The server speaks the Model Context Protocol over stdio and
nothing else: any client that can start a process and talk JSON-RPC to it (Claude Code, Cursor,
VS Code and Continue, Zed, LibreChat, a script of your own using an MCP SDK) can use it. The
Claude Desktop bundle and the installers are conveniences for one client; the server underneath is
the same console script. Register it anywhere by giving the client the absolute path of the
console script and, optionally, the environment:

```json
{
  "mcpServers": {
    "jstage": {
      "command": "/absolute/path/to/.venv/bin/jstage-mcp",
      "env": {
        "MCP_RECEIPT_DIR": "/absolute/path/to/receipts",
        "MCP_RECEIPT_SESSION": "project-or-article-slug"
      }
    }
  }
}
```

Claude Code takes the same thing on the command line:

```bash
claude mcp add jstage -- /absolute/path/to/.venv/bin/jstage-mcp
```

On Windows the path ends in `\.venv\Scripts\jstage-mcp.exe`. `MCP_RECEIPT_DIR` and `MCP_RECEIPT_SESSION`
are optional; without them the server runs and every envelope says `RECEIPT_NOT_DEPOSITED`. The
stdio transport is the only one: there is no HTTP endpoint to expose, and nothing to host.

## Troubleshooting

**"Server disconnected"** is all Claude Desktop says when the server process exited before or during the handshake, whatever the reason. The reason is in the log:

- Windows: `%APPDATA%\Claude\logs\mcp-server-<name>.log` (the extension's display name, or the key under `mcpServers`), with `mcp.log` beside it for the app's side of the conversation.
- macOS: `~/Library/Logs/Claude/mcp-server-<name>.log` and `mcp.log`.
- Linux: `~/.config/Claude/logs/`.

Read the last launch from the bottom up. Three shapes account for nearly every report:

- **A Python traceback ending in `ImportError` or `ModuleNotFoundError`** (for example `No module named 'pydantic_core._pydantic_core'`). The interpreter started, the code was found, and a compiled library did not match that interpreter. This is what every bundle before 3.1.0 did on any Python other than 3.12. Install the current bundle, or use the pip route, which resolves wheels for the interpreter you install into.
- **`'python' is not recognized`, `spawn python ENOENT`, or a line from the Microsoft Store**: no interpreter was found on the PATH Claude Desktop constructs. Nothing of this server ran. The current bundle does not launch `python` at all; for the pip route, register the console script by absolute path as shown above.
- **A line from uv** (`error: ...`, or a download that never finished): the current bundle's runtime could not build its environment, usually because the first launch had no network or ran past Claude Desktop's sixty-second limit. Restart the app; uv keeps what it fetched. A uv older than 0.5 cannot read the lock file; upgrade it or remove it so the app uses its own.

The bundle's own entry point writes one line naming the interpreter, its path and the supported range before re-raising an import failure, so a log from 3.1.0 onwards says which of these it is.

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

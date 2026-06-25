# jstage-mcp

A FastMCP stdio server exposing the [J-STAGE WebAPI](https://www.jstage.jst.go.jp/static/pages/JstageServices/TAB3/-char/en) as four tools for use with Claude Desktop.

## Tools

| Tool | Purpose |
| --- | --- |
| `jstage_search_articles` | Full-text / author / title / journal search across J-STAGE articles |
| `jstage_list_issues` | Volume & issue spine for a known title, ISSN, or `cdjournal` |
| `jstage_search_journals` | Find journals by title / ISSN / publisher (see *Limitations*) |
| `jstage_get_article_by_doi` | Resolve a J-STAGE DOI to its full article record |

All tools return JSON with bilingual (English / Japanese) titles, authors, and journal names where J-STAGE provides them. Every response includes a `powered_by` field per the JST attribution requirement.

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

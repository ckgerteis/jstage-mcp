"""jstage-mcp — MCP server for J-STAGE.

Importing this package does not start the server; call `main()`, run
`python -m jstage_mcp`, or use the installed `jstage-mcp` console script.
"""
from .server import __version__, main

__all__ = ["main", "__version__"]

"""The `ledger mcp` subcommand. Kept apart from cli.py so the CLI never
imports the MCP SDK unless asked to serve."""
from __future__ import annotations

from ledger.cli import EXIT_OK, CliError


def cmd_mcp(args) -> int:
    try:
        from ledger import mcp_server
    except ImportError as e:
        raise CliError(
            "the MCP SDK is not installed for this interpreter. From the project directory run "
            "python3 -m venv .venv && .venv/bin/pip install -e '.[mcp]' (staff build ledger does this), "
            f"or point LEDGER_PYTHON at an interpreter that has it. ({e})")
    return mcp_server.main() or EXIT_OK


def add_commands(sub) -> None:
    s = sub.add_parser("mcp", help="serve the MCP server over stdio (for Claude Code / Claude Desktop)")
    s.set_defaults(fn=cmd_mcp)

"""Write manifest.json, taking the tool list from the server itself so the two cannot drift."""

import asyncio
import json
import os
import pathlib
import sys

LONG_DESCRIPTION = (
    "Ask about Delta Exchange India in plain English: live prices, option chains, "
    "order books, funding and open-interest history, plus your own positions, orders, "
    "fills and balances.\n\n"
    "**Read-only.** This cannot place, change or cancel orders, and cannot move funds.\n\n"
    "**Both credential fields or neither.** A key without its matching secret is ignored "
    "and you get market data only — the two are always used together.\n\n"
    "**Market data needs no setup** — leave the API key and secret empty and everything "
    "except your own account still works.\n\n"
    "**To see your account**, create a key at delta.exchange under Account → API Keys with "
    "the **Read Data** permission. Both halves are shown only once, at creation. Paste them "
    "into Configure. Your key is stored by this app and is sent only to Delta's API, from "
    "your own machine.\n\n"
    "**Environment** must be `india_prod` for the real exchange, or `india_testnet` for the "
    "practice site at demo.delta.exchange. A key only works against the site it was made on."
)

# Claude Desktop renders each description twice: as help text under the label AND as the
# input placeholder, where anything past ~60 characters is truncated mid-word. Keep these
# short enough to read cleanly in both roles; the detail lives in LONG_DESCRIPTION.


async def tool_entries() -> list[dict[str, str]]:
    """Introspect the server with placeholder credentials so the account tools register."""
    os.environ.setdefault("DELTA_API_KEY", "placeholder")
    os.environ.setdefault("DELTA_API_SECRET", "placeholder")
    from delta_exchange_mcp.server import build_server

    tools = await build_server().list_tools()
    return [
        {
            "name": t.name,
            "description": (t.description or "").strip().splitlines()[0].strip(),
        }
        for t in sorted(tools, key=lambda t: t.name)
    ]


def manifest(version: str, tools: list[dict[str, str]]) -> dict:
    return {
        "manifest_version": "0.4",
        "name": "delta-exchange-mcp",
        "display_name": "Delta Exchange",
        "version": version,
        "description": "Live market data and your Delta Exchange India account, read-only.",
        "long_description": LONG_DESCRIPTION,
        "author": {"name": "Delta Exchange", "url": "https://www.delta.exchange"},
        "repository": {
            "type": "git",
            "url": "https://github.com/delta-exchange/delta-exchange-mcp",
        },
        "homepage": "https://www.delta.exchange",
        "documentation": "https://github.com/delta-exchange/delta-exchange-mcp#readme",
        "support": "https://github.com/delta-exchange/delta-exchange-mcp/issues",
        "icon": "icon.png",
        "license": "MIT",
        "keywords": ["trading", "crypto", "options", "futures", "market-data"],
        "server": {
            "type": "uv",
            "entry_point": "server/main.py",
            "mcp_config": {
                "command": "uv",
                "args": [
                    "run",
                    "--directory",
                    "${__dirname}",
                    "--frozen",
                    "python",
                    "server/main.py",
                ],
                "env": {
                    # Pinned, not omitted: the client merges this over the environment it
                    # was launched with, so an ambient DELTA_MCP_MODE=trade would otherwise
                    # register the mutation tools in a bundle that promises read-only.
                    "DELTA_MCP_MODE": "read",
                    "DELTA_MCP_ENV": "${user_config.environment}",
                    "DELTA_API_KEY": "${user_config.api_key}",
                    "DELTA_API_SECRET": "${user_config.api_secret}",
                },
            },
        },
        "tools": tools,
        "tools_generated": False,
        "user_config": {
            "api_key": {
                "type": "string",
                "title": "API key",
                "description": "Optional — leave empty for market data only.",
                "sensitive": True,
                "required": False,
            },
            "api_secret": {
                "type": "string",
                "title": "API secret",
                "description": "Required if you filled in the key above.",
                "sensitive": True,
                "required": False,
            },
            "environment": {
                "type": "string",
                "title": "Environment",
                "description": "india_prod (real) or india_testnet (practice).",
                "default": "india_prod",
                "required": True,
            },
        },
        "compatibility": {
            "claude_desktop": ">=0.10.0",
            "platforms": ["darwin", "win32", "linux"],
            "runtimes": {"python": ">=3.12"},
        },
    }


def main() -> None:
    out = pathlib.Path(sys.argv[1])
    version = sys.argv[2]
    tools = asyncio.run(tool_entries())
    out.write_text(json.dumps(manifest(version, tools), indent=2) + "\n")
    print(f"wrote {out.name} ({len(tools)} tools, version {version})")


if __name__ == "__main__":
    main()

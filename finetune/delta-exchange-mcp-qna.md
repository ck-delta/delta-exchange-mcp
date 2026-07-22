# Delta Exchange MCP — Q&A dataset

Question-and-answer pairs for fine-tuning a Claude model on [delta-exchange-mcp](https://github.com/delta-exchange/delta-exchange-mcp), the official MCP server for Delta Exchange India.

Questions use Simplified Technical English (short, one idea, active voice). Answers are comprehensive and grounded in the repository source and the docs at https://mcp-docs-silk.vercel.app/docs. The machine-readable training file is `delta-exchange-mcp-qna.jsonl` (Claude messages format). Regenerate both with `python finetune/generate_qna.py`.

**160 pairs.**

## Contents

- [Overview and concepts](#overview-and-concepts)
- [Install and setup](#install-and-setup)
- [Authentication and API keys](#authentication-and-api-keys)
- [Security and safety](#security-and-safety)
- [Environment variables](#environment-variables)
- [Market-data tools](#market-data-tools)
- [Account read-only tools](#account-read-only-tools)
- [Trading tools (opt-in)](#trading-tools-opt-in)
- [Debugging and troubleshooting](#debugging-and-troubleshooting)

## Overview and concepts

### 1. What is delta-exchange-mcp?

delta-exchange-mcp is the official Model Context Protocol (MCP) server for Delta Exchange India. It lets AI assistants such as Claude Desktop, Claude Code, Cursor, Zed, and Codex query Delta Exchange market data and your own account through standardized MCP tools. It wraps Delta Exchange India's REST API and exposes it as tools the assistant can call.

### 2. What is MCP?

MCP (Model Context Protocol) is an open standard that connects AI assistants to external tools and data. The assistant discovers a set of tools from an MCP server, then calls them to read data or perform actions. delta-exchange-mcp is one such server: it presents Delta Exchange endpoints as tools that any MCP-capable client can use.

### 3. What do I get with this server?

You get 14 public market-data tools and 13 authenticated read-only account tools. You also get 13 trading tools that place, edit, and cancel orders, but they are off by default. Market-data tools always work. Account tools register when you set an API key and secret. Trading tools register only when you also set DELTA_MCP_MODE=trade.

### 4. How many tools does the server have?

The server has 40 tools in total: 14 public market-data tools, 13 authenticated read-only account tools, and 13 opt-in trading tools. Two extra status tools, get_debug_status and get_trading_status, register only when debug or trade mode is on.

### 5. Which exchange does the server support?

The server supports Delta Exchange India. Its API hosts are api.india.delta.exchange for production and the testnet host for demo. This is why the environment values are named india_prod, india_testnet, and india_devnet.

### 6. Is the server production-ready?

The server is in Beta. It works and is used internally, but the tool surface and configuration can still change. Report bugs, missing tools, or rough edges as GitHub issues; early reports shape what ships next.

### 7. What framework does the server use?

The server is built on FastMCP. Each tool is an @mcp.tool()-decorated async function. Tool groups live in src/delta_exchange_mcp/tools/ (market.py, account.py, trading.py) and register onto the FastMCP instance built in server.py.

### 8. How is the server distributed?

The server is distributed as a PyPI package named delta-exchange-mcp. You run it with uvx, which resolves the latest published version on each launch. There is no Docker image and no hosted endpoint.

### 9. What transport does the server use?

The server uses local stdio only. Your MCP client launches it as a subprocess and talks to it over standard input and output. There is intentionally no HTTP transport, no Docker image, and no shared hosted endpoint. Per-user API keys cannot safely route through a shared HTTP server, and users should be able to read the code that runs against their account.

### 10. Why is there no HTTP transport?

Per-user API keys cannot safely route through a shared HTTP server, and the financial-tool nature of the server means each user should run and read the code that acts on their own account. So the server runs as a local stdio subprocess of your MCP client. Do not add streamable-http, a transport flag, or a Dockerfile without discussing it first.

### 11. Who is this server for?

The server is for traders who want to query markets and their account through an AI assistant, for quants and developers who build on the tools, and for anyone who reconciles P&L or tax records from their own fills and transactions.

### 12. What is on the roadmap?

Now: 14 public market-data tools, 13 authenticated read-only account tools, and 13 opt-in trading tools with dry-run and an audit log. Next: richer guardrails such as notional and position-size caps and confirmation prompts.

### 13. What license does the project use?

The project ships a LICENSE file in the repository root. Check that file for the exact terms before you redistribute or build on the code.

### 14. Do I need an account to use market data?

No. The 14 public market-data tools work with no API key. You need a Delta Exchange account and an API key only for the account read-only tools and the trading tools.

## Install and setup

### 15. What do I need before I install?

You need uv installed on your machine. uv provides the uvx command that launches the server. Install uv from the Astral docs, then continue with the client setup.

### 16. How do I sanity-check the install?

Run `uvx delta-exchange-mcp --help`. uvx resolves the latest published version from PyPI and prints the CLI help. This confirms uv works and the package downloads before you wire it into a client.

### 17. How do I add the server to Claude Code?

Run:

```bash
claude mcp add delta-exchange-mcp \
  --scope user \
  --env DELTA_MCP_ENV=india_prod \
  --env DELTA_API_KEY=your-api-key \
  --env DELTA_API_SECRET=your-api-secret \
  -- uvx delta-exchange-mcp
```

`--scope user` makes the server available across all projects. The API key and secret are optional; drop them for public-data-only mode. Verify with `claude mcp list`.

### 18. How do I verify the server in Claude Code?

Run `claude mcp list`. The command lists registered MCP servers so you can confirm delta-exchange-mcp is present. Use `/mcp` inside a session to view and reconnect it.

### 19. How do I add the server to Cursor?

Edit `~/.cursor/mcp.json` (global) or `.cursor/mcp.json` in the repo root (project-scoped) and add an mcpServers entry:

```json
{
  "mcpServers": {
    "delta-exchange-mcp": {
      "command": "uvx",
      "args": ["delta-exchange-mcp"],
      "env": {
        "DELTA_MCP_ENV": "india_prod",
        "DELTA_API_KEY": "your-api-key",
        "DELTA_API_SECRET": "your-api-secret"
      }
    }
  }
}
```

Restart Cursor or open Settings then Tools & MCP to refresh.

### 20. How do I add the server to Codex?

Add this to `~/.codex/config.toml`:

```toml
[mcp_servers.delta-exchange-mcp]
command = "uvx"
args = ["delta-exchange-mcp"]
env = { DELTA_MCP_ENV = "india_prod", DELTA_API_KEY = "your-api-key", DELTA_API_SECRET = "your-api-secret" }
```

Codex uses TOML, not JSON. The API key and secret are optional.

### 21. How do I add the server to Windsurf?

Edit `~/.codeium/windsurf/mcp_config.json` (macOS/Linux) or the Windows equivalent under `%USERPROFILE%`. Use the same mcpServers JSON shape as Cursor. The UI route is Settings then Cascade then Plugins (MCP servers) then Manage Plugins then View raw config.

### 22. How do I add the server to Zed?

Edit `~/.config/zed/settings.json` (user) or `.zed/settings.json` (project). Zed uses the top-level key `context_servers` and nests `command` as an object:

```json
{
  "context_servers": {
    "delta-exchange-mcp": {
      "command": {
        "path": "uvx",
        "args": ["delta-exchange-mcp"],
        "env": {
          "DELTA_MCP_ENV": "india_prod",
          "DELTA_API_KEY": "your-api-key",
          "DELTA_API_SECRET": "your-api-secret"
        }
      }
    }
  }
}
```

Note the shape difference from other clients: the key is context_servers and command is an object with a path field.

### 23. How do I add the server to VS Code with GitHub Copilot?

Add `.vscode/mcp.json` to your workspace. The top-level key is `servers` and each entry needs an explicit `"type": "stdio"`:

```json
{
  "servers": {
    "delta-exchange-mcp": {
      "type": "stdio",
      "command": "uvx",
      "args": ["delta-exchange-mcp"],
      "env": {
        "DELTA_MCP_ENV": "india_prod",
        "DELTA_API_KEY": "your-api-key",
        "DELTA_API_SECRET": "your-api-secret"
      }
    }
  }
}
```

### 24. How do I add the server to Claude Desktop?

Open Settings then Developer then Edit config, or edit the config file directly. Add an mcpServers entry with command `uvx` and args `["delta-exchange-mcp"]`, plus the DELTA_MCP_ENV and optional key/secret env vars. Quit and relaunch Claude Desktop for changes to take effect.

### 25. Where is the Claude Desktop config file?

macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`. Windows: `%APPDATA%\Claude\claude_desktop_config.json`. Linux: `~/.config/Claude/claude_desktop_config.json`. Open it from Settings then Developer then Edit config, or edit the path directly.

### 26. Are the API key and secret required in the config?

No. DELTA_API_KEY and DELTA_API_SECRET are optional in every client snippet. Drop them to run in public-data-only mode. Set both to register the account read-only tools.

### 27. How do I run the testnet instead of production?

Set `DELTA_MCP_ENV=india_testnet` in the client env block. Use a demo key created at demo.delta.exchange, because prod and testnet keys are separate. The default is india_prod.

### 28. How do I pin a specific version?

Pin the version in the uvx invocation: `uvx "delta-exchange-mcp==0.2.0"`. Without a pin, uvx floats to the latest published PyPI version on each launch.

### 29. How do I run an unreleased branch or fork?

Swap `uvx delta-exchange-mcp` for the git form: `uvx --from git+<repo-url>@<ref> delta-exchange-mcp`. `<ref>` can be a branch, tag, or commit SHA. The git form rebuilds from source on each launch and is for testing unreleased changes.

### 30. How do I pick up new commits on the same dev branch?

Add `--refresh` to the uvx command, because uv caches the git resolution. Example: `uvx --refresh --from git+https://github.com/delta-exchange/delta-exchange-mcp.git@develop delta-exchange-mcp --help`.

### 31. How do I keep a dev server separate from the release?

Register the dev server under a different name, such as delta-exchange-mcp-dev, so it does not collide with the PyPI install. Use the git+URL form in its args and keep `uvx delta-exchange-mcp` for everyday use.

### 32. How do I update to the latest version?

1. If your config pins a version, bump the pin or drop it to float to latest. 2. Refresh the uvx cache with `uvx --refresh delta-exchange-mcp --help`. 3. Reload the server so the client respawns the process: in Claude Code run `/mcp` and reconnect, or restart the client. New tools appear only after the respawn.

### 33. Why does a new release not appear automatically?

uvx caches the resolved package, so a new PyPI release is not picked up on the next launch. Run `uvx --refresh delta-exchange-mcp --help` to fetch the new build, then reload the server in your client.

### 34. Does the list_changed notification update the package version?

No. The MCP list_changed notification refreshes the tool list of an already-running server. It does not swap the underlying package version. A version change always requires a client restart so the process respawns.

### 35. What does --scope user do in Claude Code?

`--scope user` registers the server for all your projects, not just the current one. Use it when you want delta-exchange-mcp available everywhere. Verify the registration with `claude mcp list`.

### 36. How do I install dependencies for development?

Clone the repo and run `uv sync`. It installs runtime and dev dependencies. Rerun `uv sync` after you change pyproject.toml or entry points, because uv run caches the build.

### 37. How do I run the server from source?

Run `uv run delta-exchange-mcp` from the repo. It starts the server over stdio, the only transport. For a live check against your DELTA_MCP_ENV, run `uv run python scripts/smoke.py`.

### 38. Which clients does the server support?

Claude Code, Cursor, Codex, Windsurf, Zed, VS Code with GitHub Copilot, and Claude Desktop. Each has its own config file and JSON or TOML shape, but all launch the same `uvx delta-exchange-mcp` subprocess.

## Authentication and API keys

### 39. How do I create an API key?

Create a key at delta.exchange/app/account/manageapikeys for production, or at demo.delta.exchange for testnet. Both the api_key and the api_secret are shown once at creation. Save the secret immediately.

### 40. Can I recover a lost API secret?

No. The api_secret is shown once at creation and cannot be re-derived. If you lose it, create a new key and update your client config.

### 41. Which permission does the API key need?

Read Data permission is enough for the account read-only tools. Trading permission is not required and not used by the read-only surface. Enable Trading only if you opt into trade mode.

### 42. Should I whitelist my IP on the key?

Yes, whitelisting your IP is recommended. Delta blocks non-whitelisted IPs. When the block fires, the error surfaces your current IP so you can add it in API management.

### 43. How do I match the key to the environment?

Use prod keys with DELTA_MCP_ENV=india_prod and demo keys with DELTA_MCP_ENV=india_testnet. Keys are environment-scoped on Delta's side. Mixing them returns an InvalidApiKey error.

### 44. Why do prod and testnet keys not interchange?

API keys are scoped to the environment they are created in. A prod key from delta.exchange works only against india_prod; a demo key from demo.delta.exchange works only against india_testnet. A mismatch returns InvalidApiKey.

### 45. How does the server sign requests?

The server signs each authenticated request with HMAC-SHA256. It concatenates method, timestamp, path, query, and body into the signing payload, then signs it with your api_secret. The signing path must include the /v2 prefix, which the client adds; callers pass relative paths like /orders.

### 46. What is the signature timestamp window?

Delta accepts a signature timestamp within about 5 seconds of its server clock. If your system clock drifts past that window, the request fails with SignatureExpired. Sync your clock via NTP to fix it.

### 47. How does the server sign a POST body?

The signed body must be the exact bytes sent on the wire. The client serializes the JSON body once with compact separators, signs that string, and sends the same string. It never re-serializes, because different spacing would break the signature.

### 48. Why does the server send a User-Agent header?

Delta requires a User-Agent header. A missing one returns HTTP 403. The server always sets it, and you should not remove it.

### 49. Do my API keys leave my machine?

No. The server runs as a local stdio subprocess of your client, and your keys stay on your machine. There is no shared hosted endpoint that could receive them.

### 50. Does the AI model ever see my credentials?

No. Credentials are read from your local environment and used only to sign requests to Delta. They are not sent through the AI model and are never written to the debug or audit logs.

### 51. How do I register the account read-only tools?

Set both DELTA_API_KEY and DELTA_API_SECRET in the client env block. The server registers the 13 account read-only tools only when both are present. Without them it runs in pure public mode.

### 52. What happens without credentials?

Without DELTA_API_KEY and DELTA_API_SECRET, only the 14 public market-data tools register. The account and trading tools stay off, and the server behaves as a public-data-only server.

## Security and safety

### 53. Is the server read-only by default?

Yes. Trading tools register only with the explicit DELTA_MCP_MODE=trade opt-in. Without it, every tool is a GET and the server cannot place, edit, or cancel orders.

### 54. How do I enable trading?

Set DELTA_MCP_MODE=trade in the client env block alongside a valid API key and secret. The key must have Trading enabled in Delta API management and the requesting IP whitelisted. Without the opt-in the trading tools do not register.

### 55. What is dry run?

Dry run is a flag on every mutating tool. When dry_run is true, the tool validates the request and returns the exact payload it would send, without sending it. Use it to preview an order: ask the assistant to place it as a dry run first.

### 56. What does the audit log record?

The audit log records every mutation, real or dry-run, as one JSON line: the tool, the request params, and the result or order id. It never records credentials. It is on by default in trade mode and lives in an owner-only file.

### 57. Where is the audit log?

The audit log is written to `~/.delta-exchange-mcp/audit/audit-<timestamp>-<pid>.log` with owner-only 0600 permissions. Override the path with DELTA_MCP_AUDIT_FILE. Ask the assistant "where is the audit log?"; the get_trading_status tool returns the path.

### 58. How do I disable the audit log?

Set DELTA_MCP_AUDIT to off, false, 0, or no. This kill switch disables the trading audit log. The log is on by default whenever DELTA_MCP_MODE=trade.

### 59. Does the server retry a failed mutation?

No. Unlike GET reads, mutations are never auto-retried on timeout or rate-limit. A failure is surfaced, not silently re-sent, so you never place a duplicate order by accident.

### 60. Can the server withdraw funds?

No. The server has no withdrawal functionality. Its trading tools place, edit, and cancel orders and manage positions and margin, but they cannot move funds off the exchange.

### 61. What must I redact before I share logs?

Redact api_key and api_secret from any logs or screenshots. The debug log never contains credentials or signatures, but response bodies contain your account data such as balances, positions, and transactions. Review before sharing.

### 62. Why should I read the code?

This is a financial-tool MCP that acts against your account. Read the code so you know exactly what runs. The local-only, no-hosted-endpoint design exists so you can audit the code that uses your keys.

### 63. How does the server protect the CSV export path?

The bulk_fills_export tool restricts output_path to the current working directory or your home directory, and expands `~`. It resolves the path and rejects anything outside those roots. This guards against path traversal and unexpected writes.

### 64. Are mutations auditable in dry-run too?

Yes. The audit log records dry-run calls as well as real ones, each marked as a dry run. This gives you a full record of what the assistant tried, whether or not it was sent.

## Environment variables

### 65. What does DELTA_MCP_ENV do?

DELTA_MCP_ENV selects the Delta environment. Valid values are india_prod, india_testnet, and india_devnet. The default is india_prod, because users who ask for a price usually mean production.

### 66. What does DELTA_API_KEY do?

DELTA_API_KEY holds your API key. It is optional. When set together with DELTA_API_SECRET, the account read-only tools register. Alone it does nothing.

### 67. What does DELTA_API_SECRET do?

DELTA_API_SECRET holds the API secret that matches DELTA_API_KEY. The server uses it to sign authenticated requests. It is optional and pairs with DELTA_API_KEY.

### 68. What does DELTA_MCP_MODE do?

DELTA_MCP_MODE selects read or trade. The default read is read-only. Setting trade registers the trading tools and requires a valid API key and secret.

### 69. What does DELTA_MCP_DEBUG do?

DELTA_MCP_DEBUG turns on debug logging. Set it to 1, true, yes, or on to write HTTP request URLs and response bodies to a log file. It is unset by default.

### 70. What does DELTA_MCP_DEBUG_FILE do?

DELTA_MCP_DEBUG_FILE overrides the debug log path. The default is `~/.delta-exchange-mcp/logs/debug-<timestamp>-<pid>.log`.

### 71. What does DELTA_MCP_AUDIT do?

DELTA_MCP_AUDIT controls the trading audit log. It is on by default in trade mode. Set it to off, false, 0, or no to disable the log.

### 72. What does DELTA_MCP_AUDIT_FILE do?

DELTA_MCP_AUDIT_FILE overrides the audit log path. The default is `~/.delta-exchange-mcp/audit/audit-<timestamp>-<pid>.log`.

### 73. Which environment variables are required?

None are strictly required. The server runs public market data with no variables set. Set DELTA_MCP_ENV to change environment, DELTA_API_KEY plus DELTA_API_SECRET for account tools, and DELTA_MCP_MODE=trade for trading tools.

### 74. What is the default environment?

The default DELTA_MCP_ENV is india_prod. It also defaults DELTA_MCP_MODE to read, so a server with no env vars set serves public production market data in read-only mode.

## Market-data tools

### 75. What does list_products do?

list_products lists tradable products on Delta Exchange with optional filters and returns a paginated result plus meta cursors. Filter by contract_types (perpetual_futures, call_options, put_options, futures, spot), by states (live, upcoming, expired, settled), or by expiry in YYYY-MM-DD. Page with page_size (1-500, default 100) and the after cursor.

### 76. What does get_product do?

get_product returns full product details for one symbol, such as BTCUSD or an option symbol like C-BTC-66400-010824. Pass the symbol as the only argument.

### 77. What does get_ticker do?

get_ticker returns the 24-hour ticker for one symbol: last price, volume, open interest, and mark and spot price. Pass the symbol, for example BTCUSD.

### 78. What does list_tickers do?

list_tickers returns tickers across many products. Filter by contract_types (perpetual_futures, futures, call_options, put_options) and by underlying_asset_symbols such as BTC, ETH, or SOL.

### 79. What does get_orderbook do?

get_orderbook returns an L2 orderbook snapshot for a symbol: bid and ask depth. Set depth to choose levels per side, up to 100.

### 80. What does get_recent_trades do?

get_recent_trades returns the recent public trades for a symbol. Pass the symbol as the only argument.

### 81. What does get_candles do?

get_candles returns OHLC candles for a symbol. Pass symbol, resolution (1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 1d, 1w), and start and end as inclusive Unix timestamps in seconds. For funding, mark, or open-interest history use the dedicated tools instead.

### 82. What resolutions does get_candles accept?

get_candles accepts 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 1d, and 1w. The same resolution set applies to get_funding_history, get_mark_price_history, and get_oi_history.

### 83. What does get_funding_history do?

get_funding_history returns historical funding-rate candles for a perpetual, as OHLC over the funding rate. Pass a perpetual symbol such as BTCUSD, a resolution (default 1h), and start and end timestamps. Use it for basis-trade analysis or to compute realized funding over a holding period.

### 84. What does get_mark_price_history do?

get_mark_price_history returns historical mark-price candles for a product. Pass the symbol, a resolution (default 1m), and start and end timestamps. Use it to reconstruct P&L curves or compare your fill price to fair value.

### 85. What does get_oi_history do?

get_oi_history returns historical open-interest candles for a product, as OHLC over open interest. Pass the symbol, a resolution (default 1h), and start and end timestamps. Use it to detect positioning extremes or OI build-up around events.

### 86. What does get_options_chain do?

get_options_chain returns all call and put tickers for one underlying on one expiry. Pass underlying (for example BTC or ETH) and expiry_date. Note the expiry format is DD-MM-YYYY here, which differs from the YYYY-MM-DD used by list_products.

### 87. What does get_settlement_prices do?

get_settlement_prices returns historical settlement prices for expired or settled derivatives, paginated. Each product carries settlement_time and settlement_price. Under the hood it is list_products(states=["expired"]). Use it for post-expiry P&L reconciliation or backtesting against realized settlements.

### 88. What does get_indices do?

get_indices returns the spot price indices Delta builds by combining prices from several exchanges. Each index returns its constituent exchanges and weights, its index_type (spot_pair, fixed_interest_rate, or floating_interest_rate), tick_size, and the underlying and quoting asset. Use it to audit how a mark or settlement price is built.

### 89. What does get_reference_data do?

get_reference_data returns a merged assets and indices listing, useful for symbol and asset metadata lookups. For index-only queries such as composition or weights, prefer get_indices.

### 90. How do I get the mark price and 24h range for BTCUSD?

Ask the assistant for the BTCUSD mark price and 24h range. It calls get_ticker with symbol BTCUSD, which returns last price, 24-hour stats, mark price, and open interest. You do not name the tool; the assistant picks it.

### 91. How do I see the option chain for a Friday expiry?

Ask for the options chain for the underlying and expiry, for example "the BTC options chain for this Friday." The assistant calls get_options_chain with underlying BTC and the expiry_date in DD-MM-YYYY.

### 92. How do I list only live perpetuals?

Ask for live perpetual products. The assistant calls list_products with contract_types=["perpetual_futures"] and states=["live"], then pages with the after cursor if there are more than page_size results.

## Account read-only tools

### 93. What does get_positions do?

get_positions returns open position(s). Pass exactly one of product_id or underlying_asset_symbol. It returns only entry_price and size. For analytical fields such as unrealized_pnl, margin, mark_price, and liquidation_price, use get_margined_positions instead.

### 94. What does get_margined_positions do?

get_margined_positions returns all open margined positions, optionally filtered by product_ids (max 10) or contract_types. It includes size (signed: positive long, negative short), entry and mark price, margin, and unrealized P&L. It also fixes the short-option P&L bug client-side.

### 95. How do I compute notional exposure for a position?

Use notional_usd = abs(size) * contract_value * index_price. Use index_price, the spot of the underlying, not mark_price. For an option, mark_price is the premium, so multiplying by it gives the premium value, not the underlying exposure. Example: a short BTC call with size 10, contract_value 0.001, and BTC index 54270 has notional 10 * 0.001 * 54270 = $542.70.

### 96. Why does the server patch short-option P&L?

The upstream API returns an unsigned unrealized_pnl (the premium value) for short option positions, ignoring direction. get_margined_positions recomputes the signed P&L client-side as (mark_price - entry_price) * size * contract_value, with size signed. Futures and long options pass through unchanged. This is GitHub issue #9.

### 97. What does get_wallet_balances do?

get_wallet_balances returns balances across all assets. Fields: asset_symbol, balance, available_balance, position_margin, and strategy_blocked_amount.

### 98. What is strategy_blocked_amount?

strategy_blocked_amount is collateral reserved by an active Algo Marketplace strategy subscription. It is normal and expected, not a risk or anomaly. To release it, stop or unsubscribe from the strategy.

### 99. What does get_wallet_transactions do?

get_wallet_transactions returns paginated wallet transaction history with microsecond timestamps. Filter by asset_ids, transaction_types (deposit, withdrawal, funding, settlement, commission, and more), and a time window. Default page_size is 50 (max 200).

### 100. What does get_fills do?

get_fills returns your executed trade fills, paginated, with microsecond timestamps. Filter by product_ids, contract_types, and a time window. Default page_size is 50 (max 200). For full-history analysis prefer bulk_fills_export.

### 101. Why does a fills or transactions query look empty?

If you omit start_time_us, the API returns only the last ~90 days, so older records are not included and a short result is not proof that nothing exists. Pass an explicit start_time_us in microseconds to reach older history. When you omit it, the result carries a notice field saying so. This is GitHub issue #18.

### 102. What time unit do the account tools use?

The account history tools use microseconds epoch, not milliseconds. start_time_us and end_time_us are microseconds. This applies to get_fills, get_wallet_transactions, get_order_history, and bulk_fills_export.

### 103. What does get_open_orders do?

get_open_orders returns current open and pending orders, paginated via meta.after and meta.before. Filter by product_ids (max 10), states (open, pending), and contract_types. Default page_size is 50 (max 200).

### 104. What does get_order_history do?

get_order_history returns closed and cancelled orders, filterable and paginated, with microsecond timestamps. Filter by product_ids, contract_types, and order_types (market, limit, stop_market, stop_limit, all_stop) plus a time window.

### 105. What does get_order_by_id do?

get_order_by_id fetches a single order. Pass exactly one of order_id (the Delta-assigned id) or client_order_id (your own id). It resolves the correct endpoint for each.

### 106. What does get_product_leverage do?

get_product_leverage returns the configured order leverage for a product. Pass the product_id. This is a read; to change leverage you need the trading tool set_product_leverage.

### 107. What does get_trading_stats do?

get_trading_stats returns account-level trading volume and statistics. It takes no arguments.

### 108. What does get_trading_preferences do?

get_trading_preferences returns your trading preferences, such as margin mode and notification settings. It takes no arguments.

### 109. What does get_profile do?

get_profile returns your user profile. It takes no arguments. The trading tools also use the profile internally to resolve your user_id for close_all_positions.

### 110. What does bulk_fills_export do?

bulk_fills_export writes your fills to a CSV file on disk and returns {path, row_count, size_bytes}. Use it for full-history analysis, tax reports, or backtesting, where paginated get_fills would need many round-trips. output_path must be inside the current working directory or home directory.

### 111. How do I export a full year of fills for tax?

Call bulk_fills_export with an explicit start_time_us and usually end_time_us in microseconds. Without start_time_us the export covers only the last ~90 days and silently misses older trades. Set output_path inside your cwd or home directory.

### 112. How do I get unrealized P&L for my positions?

Use get_margined_positions, not get_positions. get_positions returns only entry_price and size, while get_margined_positions returns unrealized_pnl, margin, mark_price, and liquidation_price, with short-option P&L corrected.

## Trading tools (opt-in)

### 113. When do the trading tools register?

The trading tools register only when DELTA_MCP_MODE=trade is set alongside valid credentials. Without the opt-in the server stays read-only and the trading tools do not appear.

### 114. What does place_order do?

place_order places a single order. Pass size, side (buy or sell), order_type (limit_order or market_order), and exactly one of product_id or product_symbol. limit_price is required for limit_order and rejected on market_order. For stop orders set stop_order_type and stop_price or trail_amount. You can attach a bracket with the bracket_* params.

### 115. What does edit_order do?

edit_order edits an open order. Pass id, the new total size, and exactly one of product_id or product_symbol. You can update limit_price, stop_price, trail_amount, and post_only. order_type cannot change on an edit. Prices are rounded to the product's tick.

### 116. What does cancel_order do?

cancel_order cancels a single order. Pass product_id plus exactly one of id or client_order_id.

### 117. What does cancel_all_orders do?

cancel_all_orders cancels open orders. With no filters it cancels ALL of your open orders. Narrow it with product_id or contract_types, and with the cancel_limit_orders, cancel_stop_orders, and cancel_reduce_only_orders flags. When you set none of the three flags, the tool defaults all three to true so "cancel all" actually cancels everything.

### 118. What does place_batch_orders do?

place_batch_orders places up to 50 orders on one contract in a single request. Pass orders as a list, each {size, side, order_type, limit_price?, time_in_force?, post_only?, client_order_id?}, plus one of product_id or product_symbol. All orders must be on the same contract. IOC and stop orders are not allowed in a batch, and each client_order_id must be unique within the batch.

### 119. What does edit_batch_orders do?

edit_batch_orders edits up to 50 orders on one contract in a single request. Pass orders as a list, each {id, size, order_type, limit_price?, post_only?}, plus one of product_id or product_symbol.

### 120. What does cancel_batch_orders do?

cancel_batch_orders cancels up to 50 orders on one contract in a single request. Pass orders as a list, each {id} or {client_order_id}, plus one of product_id or product_symbol.

### 121. What is the batch size limit?

The batch limit is 50 orders per request, for place_batch_orders, edit_batch_orders, and cancel_batch_orders. A larger list is rejected with a clear error before any call is sent. All orders in a batch must be on the same contract.

### 122. How does a batch report a partial failure?

Delta's batch endpoints return only the processed orders with no per-index error. When fewer orders come back than were sent, the tool attaches a partial_failure block with requested, succeeded, dropped counts, and the dropped ids or client_order_ids it can identify. It still returns the orders that succeeded. This is BUG-2.

### 123. What does place_bracket_order do?

place_bracket_order attaches a take-profit and stop-loss bracket to a position. Pass one of product_id or product_symbol and at least one of stop_loss_order or take_profit_order. These legs are not editable via edit_bracket_order; cancel and re-place to change them.

### 124. What does edit_bracket_order do?

edit_bracket_order edits the bracket TP/SL params on an existing order. id is the entry-order id, an order created with bracket_* params (for example via place_order with bracket_take_profit_price). It does not accept the leg ids of a position bracket created by place_bracket_order.

### 125. What is the difference between the two bracket tools?

place_bracket_order attaches a bracket to an open position; those legs are not editable and you cancel and re-place to change them. An entry-order bracket, created by passing bracket_* params to place_order, is editable via edit_bracket_order using the returned order id. Pick the entry-order bracket when you want to edit later.

### 126. What does set_product_leverage do?

set_product_leverage sets the order leverage for a product. Pass product_id and leverage as a string, for example '10'. Read the current value with the account tool get_product_leverage.

### 127. What does adjust_position_margin do?

adjust_position_margin adds or removes isolated margin on a position. Pass product_id and delta_margin as a string: positive adds margin, negative removes it, for example '5.0' or '-5.0'.

### 128. What does close_all_positions do?

close_all_positions closes open positions in the scopes you set to true: close_all_portfolio for cross/portfolio-margined positions and close_all_isolated for isolated-margin positions. Both default to false, so you must opt into a scope. Your user_id is resolved automatically from your profile; you do not pass it.

### 129. Do I pass user_id to close_all_positions?

No. The API needs a user_id, but the tool resolves it automatically from your profile, fetches it once, and caches it per process. user_id is never a tool parameter.

### 130. What does configure_auto_topup do?

configure_auto_topup overrides auto top-up for a single position. Pass product_id and auto_topup as a boolean. Without an override, the position inherits the account setting.

### 131. How do I preview an order before I send it?

Set dry_run to true, or ask the assistant to place the order as a dry run first. The tool validates the request and returns {dry_run, method, path, payload} without sending it. Every mutating tool supports dry_run.

### 132. Does the server round my order price?

Yes. Order and bracket prices are rounded to the product's tick size. The tool looks up tick_size (cached per process), snaps each price to the nearest multiple, and reports any changes in a price_adjustments field on the response (adjustments on a dry-run echo). A metadata-lookup failure never blocks the order.

### 133. How are boolean order flags encoded?

Order-level flags such as post_only, reduce_only, and the cancel_* flags are Delta string enums, so the tool sends "true" or "false" strings. Position-level flags such as auto_topup and the close_all_* flags are real JSON booleans.

### 134. What does the time_in_force parameter accept?

time_in_force on place_order accepts gtc (good till cancelled) or ioc (immediate or cancel). Note that IOC and stop orders are not allowed inside a batch order request.

### 135. What does post_only do?

post_only rejects an order if it would take liquidity, keeping you a maker. It is a boolean on place_order and edit_order. The server sends it as a Delta string enum.

### 136. What does reduce_only do?

reduce_only makes an order only reduce an existing position, never increase or flip it. It is a boolean on place_order, sent as a Delta string enum.

### 137. What stop-trigger methods are available?

Stop orders and brackets accept stop_trigger_method values mark_price, last_traded_price, and spot_price. Use it on place_order stop orders and on the bracket tools via bracket_stop_trigger_method.

### 138. Can a bracket stop-loss use both a price and a trailing amount?

No. A bracket stop-loss is either a fixed trigger price or a trailing amount, never both. The tool guards this client-side and fails fast, even in dry-run, with a clear message instead of spending a live round-trip on a rejection.

## Debugging and troubleshooting

### 139. How do I turn on debug logging?

Set DELTA_MCP_DEBUG=1 in your client env block, restart the client, and re-run the action. Each HTTP call, its request URL with filter params, response body, and status logs to `~/.delta-exchange-mcp/logs/`. The exact path prints on startup.

### 140. Where is the debug log?

The debug log is at `~/.delta-exchange-mcp/logs/debug-<timestamp>-<pid>.log`, or the path in DELTA_MCP_DEBUG_FILE. The path prints in the stderr startup banner. You can also ask the assistant "where is the debug log?"; the get_debug_status tool returns it.

### 141. Does the debug log contain my secrets?

No. The debug log never contains your API key, secret, or request signatures; those live only in headers, which are never logged. But response bodies do contain your account data such as balances, positions, and transactions, so review before sharing.

### 142. What does get_debug_status do?

get_debug_status reports the debug log path. It registers only when debug is on. Ask the assistant where the debug log is and it calls this tool.

### 143. What does get_trading_status do?

get_trading_status reports {mode, audit_log_path}. It registers only in trade mode. Ask the assistant where the audit log is and it calls this tool.

### 144. How do I fix a SignatureExpired error?

SignatureExpired means the request signature drifted more than about 5 seconds from Delta's clock. Sync your system clock via NTP. The signature timestamp must fall within Delta's roughly 5-second window.

### 145. How do I fix an InvalidApiKey error?

InvalidApiKey means the API key was not found for this environment. Prod and testnet keys are separate, so confirm DELTA_MCP_ENV matches the dashboard the key was created on: prod keys with india_prod, demo keys with india_testnet.

### 146. How do I fix an UnauthorizedApiAccess error?

UnauthorizedApiAccess means the API key lacks permission for that endpoint. Enable Read Data, or Trading if you use trade mode, on the key in Delta API management.

### 147. How do I fix an ip_not_whitelisted_for_api_key error?

This error means your request IP is not whitelisted for the key. Add the IP shown in the error context under Delta API management. The server extracts and reports that IP in the error message.

### 148. How do I fix a Signature Mismatch error?

Signature Mismatch is usually clock skew or a path or query encoding bug. First sync your clock via NTP. If it persists, capture the debug log and file an issue, because it may indicate a signing-path problem.

### 149. Why does a tool return HTTP 403?

A 403 with no other cause usually means a missing User-Agent header, which Delta requires. The server always sets it, so if you see 403 check that you did not remove the header and that your IP is whitelisted.

### 150. Why do new tools not appear after an update?

New tools appear only after the client respawns the server process. Refresh the uvx cache with `uvx --refresh delta-exchange-mcp --help`, then reload: in Claude Code run `/mcp` and reconnect, or restart the client. The list_changed notification alone does not swap the package version.

### 151. Why does the trading tool set not appear?

The trading tools register only when DELTA_MCP_MODE=trade is set together with a valid API key and secret. Confirm all three are set in the client env block and that you restarted the client so the process respawned.

### 152. Why does an account tool not appear?

The account read-only tools register only when both DELTA_API_KEY and DELTA_API_SECRET are set. Confirm both are present, then restart the client to respawn the server.

### 153. How do I report a bug?

Set DELTA_MCP_DEBUG=1, reproduce the issue, and open a GitHub issue at github.com/delta-exchange/delta-exchange-mcp/issues. Attach the relevant debug log lines and redact api_key and api_secret first. Report incorrect data, auth or signing errors, crashes, missing tools, or rough edges.

### 154. How do I test tools with MCP Inspector?

Use scripts/inspect.sh. For a CLI call: `bash scripts/inspect.sh --cli --method tools/list`, or `bash scripts/inspect.sh --cli --method tools/call --tool-name get_ticker --tool-arg symbol=BTCUSD`. Run `bash scripts/inspect.sh` with no args for the web UI on http://localhost:6274.

### 155. How do I run the test suite?

Run `uv run pytest`. The suite uses respx to mock httpx, so it needs no network. Run a single test by node id, for example `uv run pytest tests/test_market_tools.py::test_429_retries_then_succeeds`.

### 156. How do I lint the code?

Run `uv run ruff check src tests scripts`. Add `--fix` to autofix. Run lint and tests before you commit.

### 157. How do I run a live smoke test?

Run `uv run python scripts/smoke.py`. It hits the real environment set in DELTA_MCP_ENV. Live checks are run manually, not in CI, because the unit tests are network-free.

### 158. How does the server handle rate limits?

On HTTP 429, GET requests back off using the X-RATE-LIMIT-RESET header in milliseconds. On 5xx, GET requests use exponential backoff. Only GET is retried; POST, PUT, and DELETE mutations never auto-retry.

### 159. How does the server surface a Delta API error?

When the API returns {success: false, error: {code, context}}, the server raises a DeltaApiError with the code, context, and HTTP status. For documented auth codes it adds a human hint, and for the IP-whitelist case it extracts the request IP from the context.

### 160. Why does a filter like empty expiry fail?

Delta's API rejects an empty query param such as `?expiry=` as an invalid date. The client strips None-valued params before both signing and sending, so an unset filter is dropped rather than sent empty. This keeps the signed payload and the wire request identical.

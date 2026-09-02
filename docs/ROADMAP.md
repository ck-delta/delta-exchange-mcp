# Roadmap: engineering for the 90-day launch

Source of truth for the four engineering phases in the September 2026 marketing plan. Each line is one issue. Tick it when the PR merges.

Audit baseline (2026-09-02, v0.6.0): stdio only (`server.py`), 40 tools (14 market, 13 account, 13 trading), 17 test files / 122 tests, CI = ruff + pytest + `.mcpb` bundle, client badges in README. `dry_run` on every mutation, audit log, scope flags on `cancel_all_orders` / `close_all_positions`, mode gating via `DELTA_MCP_MODE=trade`.

## E1 · Weeks 1-2 · Registry and trust (small)

- [ ] `server.json` for the official MCP registry, DNS-verified namespace, `mcp-publisher publish`.
- [ ] `.github/workflows/publish.yml`: PyPI trusted publisher on tag, pinned action SHAs like `bundle.yml`.
- [ ] `SECURITY.md`: prompt-injection and tool-poisoning stance, no withdrawal path in any mode, disclosure contact.
- [ ] `CHANGELOG.md` back-filled from tags.
- [ ] `readOnlyHint` / `destructiveHint` / `title` annotation on every tool. Required by the Claude Connectors Directory.
- [ ] `tests/test_client.py`: retry and 429 handling. `tests/test_errors.py`: hint mapping.
- [ ] Submit to PulseMCP, Glama, mcp.so, `punkpeye/awesome-mcp-servers`.

## E2 · Weeks 2-5 · Trading guardrails (medium)

- [ ] `pause_trading` tool: revokes the session lease at runtime, no restart. Reverse with `resume_trading`.
- [ ] `DELTA_MCP_MAX_NOTIONAL`, `DELTA_MCP_MAX_LEVERAGE`, `DELTA_MCP_MAX_ORDERS_PER_SESSION`, enforced in `mutation_tool` and `_finish`. Off by default. Docs recommend setting them.
- [ ] Confirm before send: MCP elicitation where the client supports it, fallback `dry_run` preview plus `confirm=true` parameter. Never depend on elicitation alone.
- [ ] `DELTA_MCP_REDUCE_ONLY=1` safe mode.
- [ ] README: replace "no size cap" with the caps section.

## E3 · Weeks 3-8 · Hosted read-only remote (large)

- [ ] `http_server.py`: Streamable-HTTP transport (FastMCP / Starlette).
- [ ] OAuth 2.1 + PKCE against Delta login. Dependency: Delta auth team.
- [ ] Per-request credential threading through `client.py` and `config.py`; per-tenant state replaces the `store.py` and `audit_log.py` singletons.
- [ ] Hosted endpoint registers the 27 read tools only. Trading stays local self-host.
- [ ] `Source: delta-exchange-mcp-hosted/<version>` header so gateway logs split hosted from local.
- [ ] Privacy policy page and reviewer test account.
- [ ] Claude Connectors Directory submission (week 7). OpenAI Apps SDK submission after finance rules are confirmed.

## E4 · Ongoing · DX

- [ ] Tool descriptions with one example each.
- [ ] `analyze_pnl` tool (FIFO plus metrics, stdlib only).
- [ ] Rebase `feat/skills` onto upstream main and open the PR.

## Not in scope before day 90

Hosted trading. Needs legal sign-off and a ring-fenced sub-account design first.

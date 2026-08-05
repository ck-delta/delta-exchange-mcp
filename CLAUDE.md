# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project in one line

FastMCP server (stdio only) that wraps Delta Exchange India's REST API as MCP tools — public market data unconditionally, authenticated read-only account tools when `DELTA_API_KEY`/`DELTA_API_SECRET` are set, plus authenticated trading mutations when `DELTA_MCP_MODE=trade` is also set.

## Style

Don't add typing slop. In particular:

- Don't annotate pytest fixtures (`tmp_path`, `monkeypatch`, etc.) — pytest discovers them by name, the annotation adds nothing.
- Don't write `**kwargs: Any` / `-> Any` on internal test helpers. If the only honest type is `Any`, leave it off.
- Use `Any` only when it carries real information: a public boundary that genuinely accepts arbitrary JSON, a return type that is genuinely heterogeneous. Otherwise prefer the real type or no annotation at all.
- Don't add `from typing import Any` just to satisfy a redundant annotation.

## Commands

```bash
uv sync                                        # install deps (runtime + dev)
uv run pytest                                  # run full suite (asyncio_mode=auto)
uv run pytest tests/test_market_tools.py::test_429_retries_then_succeeds  # single test
uv run ruff check src tests scripts            # lint
uv run ruff check --fix src tests scripts      # lint + autofix

uv run delta-exchange-mcp                      # stdio (the only transport)

uv run python scripts/smoke.py                 # live smoke against DELTA_MCP_ENV

bash scripts/inspect.sh --cli --method tools/list
bash scripts/inspect.sh --cli --method tools/call --tool-name get_ticker --tool-arg symbol=BTCUSD
bash scripts/inspect.sh                                                          # Inspector web UI on :6274
```

**Rebuilding the editable install after changing `pyproject.toml` or entry points**: `uv sync` again — `uv run` caches the build.

## Architecture

### Tool registration pattern

Each tool module exposes `register(mcp: FastMCP, client: DeltaClient) -> None` that attaches `@mcp.tool()`-decorated closures. `server.py::build_server()` instantiates `DeltaClient` once and passes it into every `register` call. **To add a tool group**: create `src/delta_exchange_mcp/tools/<group>.py` with a `register(mcp, client)`, then call it from `build_server`.

`market.register` always runs; `account.register` runs only when `cfg.has_credentials` is true (both `DELTA_API_KEY` **and** `DELTA_API_SECRET` set).

### Bringing the account surface up without a restart

A credential saved through the in-chat form arrives in the running process, so `build_server` closes over an `activate(session)` callback and hands it to `form.register`. On the first save it calls `account.register` with a `DeltaClient` built from a freshly loaded config, then `session.send_tool_list_changed()`. It returns whether anything is still outstanding, which is what decides between "your account tools are live in this session" and "restart this client" in the message the form shows.

Three things here are load-bearing:

- **The capability has to be declared.** `serve()` runs stdio with `initialization_options(mcp)`, which passes `NotificationOptions(tools_changed=True)`. FastMCP's own `run_stdio_async` leaves every flag off, so the server would advertise `tools.listChanged: false` and a client would never re-read the tool list — the notification would be silently useless. `main` therefore calls `anyio.run(serve, mcp)`, **not** `mcp.run()`. Regression test: `test_the_server_declares_that_its_tool_list_can_change`.
- **Trade mode is never activated this way.** `activate` registers reads only and reports False when `mode == "trade"`, so arming order placement still follows from the client config the user edited. Regression test: `test_trade_mode_still_waits_for_a_restart`.
- **A rotation reports False and means it.** Already-registered account tools hold a `DeltaClient` built from the key being replaced, and nothing rebuilds them, so replacing a key in use genuinely needs the restart.

`get_connection_status` is registered unconditionally and reports `{environment, credentials_configured, account_tools_available, mode, restart_required}` — never a key or secret. It exists because `save_credentials` is hidden from the model, so after a save the model cannot see whether it worked; without this it has no way to answer "am I connected?". `credentials_configured` re-reads the file rather than reporting startup state, since another client on the machine shares it.

`FastMCP` is constructed with `instructions=INSTRUCTIONS`, which is the only channel that reaches the model when no key is configured — there is no account tool then to carry a hint on its own description.

### DeltaClient — single point for HTTP concerns

`src/delta_exchange_mcp/client.py` centralizes the cross-cutting behaviors every tool depends on. Read this file before touching any tool logic:

1. **None-param stripping** — `filtered_params` is computed once and fed to **both** the signing payload (`query_str`) and `httpx.request(params=...)`. Delta's API rejects `?expiry=` as "invalid date"; this is why the same filter applies in two places. Regression test: `test_none_params_are_stripped_before_send`.
2. **Retry policy** — 429 backs off using the `X-RATE-LIMIT-RESET` header (ms); 5xx uses exponential backoff. Only retries GET; POST/PUT/DELETE never auto-retry.
3. **Error-envelope unwrapping** — `{success: false, error: {code, context}}` is raised as `DeltaApiError` (see `errors.py`). `errors.py` carries a hint table for documented auth codes (`SignatureExpired`, `InvalidApiKey`, `UnauthorizedApiAccess`, `ip_not_whitelisted_for_api_key`, `Signature Mismatch`) and extracts the request IP from the error context for the IP-whitelist case.
4. **HMAC-SHA256 signing** — `sign()` concatenates `method + timestamp + path + query + body`. The signing path **must include the `/v2` prefix** per Delta's spec; the client derives it once from `urlparse(base_url).path` and prepends it before calling `sign()`. Don't pass `path="/v2/..."` from callers — they pass relative paths like `/orders`, the client adds the prefix.
5. **Body signing (POST/PUT/DELETE)** — the signed `body` must be the **exact bytes sent on the wire**. `_request` serializes `json_body` once with `json.dumps(..., separators=(",", ":"))`, signs that string, and sends the **same** string via `httpx.request(content=...)`. Do **not** switch back to `json=json_body` — httpx would re-serialize with different spacing and the signature would mismatch. Same "compute once, feed both" rule as None-param stripping (#1). Regression test: `test_place_order_signs_exact_body_bytes`. Convenience methods: `post()` / `put()` / `delete()`.
6. **User-Agent header is required by Delta** — a missing one returns 403. Do not remove it.

### Auth surface registration

`tools/account.py` exposes the authenticated read-only tools (positions / margined-positions / wallet-balances / wallet-transactions / fills / bulk-fills-export / open-orders / order-history / order-by-id / product-leverage / trading-stats / trading-preferences / profile). All call `client.get(..., auth=True)`.

`server.build_server()` registers them only when both creds are present. Without creds, the server runs in pure-public mode — same behaviour as before this surface existed.

### Credential entry

Three front-ends fill one file, `~/.delta-exchange-mcp/config.env`:

- `store.py` owns the file — `path/read/ensure/write/insecure_permissions`. `ensure` creates it `0600` from a commented `TEMPLATE` on first run; `write` goes through dotenv's `set_key` so comments and unrelated settings survive. `config.setting(name)` resolves the process environment first and this file second, with empty meaning unanswered (a bundle substitutes every declared variable whether or not the field was filled).
- `credentials.py` is the shared domain: `check(env, key, secret)` makes one `/profile` call, and `save(...)` writes the key, secret and environment together. Neither front-end owns these. `Check.code` carries Delta's own error code beside the rendered message so a caller can branch on which failure it was without matching on that message's text.
- `credentials.overridden_by_client()` names the settings in the shared file that the process environment is beating, and both front-ends report it — `login` as a note on stderr, the form as an `overridden` status. Without it a save is silently useless: `config` resolves the environment first, so a client passing its own key (the bundle's `user_config`, VS Code's `inputs`, an edited Cursor entry) wins on every launch, and the form would verify one account, name it, and leave the server signing with another. **It compares what `config` resolves against what the file holds, never mere presence** — the Cursor install link sets `DELTA_MCP_ENV` for everyone, so a presence test would tell every Cursor user their working key was ignored. Regression test: `test_a_client_pinning_the_same_environment_is_not_reported`.
- `login.py` is the terminal front-end. It refuses a non-TTY stdin on purpose — `getpass` reads a pipe rather than rejecting it, so `echo $KEY | ... login` would put the secret in shell history.
- `form.py` is the in-chat front-end, an **MCP App** (SEP-1865): a `ui://` HTML resource with mime `text/html;profile=mcp-app`, opened by `setup_credentials` via `_meta.ui.resourceUri`, submitting to `save_credentials` which is hidden from the model by `_meta.ui.visibility: ["app"]`. Its `register(mcp)` takes no `DeltaClient` — `credentials.check` builds its own from the candidate key. Three constraints were established empirically against Claude Desktop and Codex desktop and must not regress: **inline every asset** (both hosts' CSP blocks external fetches, and one CDN reference blanks the frame); **complete the `ui/initialize` → `ui/notifications/initialized` handshake** or the frame stays collapsed; and **never feature-test on the `io.modelcontextprotocol/ui` capability** — Claude Desktop renders these views without advertising it. The view must never call `ui/message` or `ui/update-model-context`, which would hand the typed credential to the model. Regression tests: `tests/test_form.py`.

### The view's own three rules

Read `src/spec.types.ts` in `modelcontextprotocol/ext-apps` before changing any of these; each was wrong once.

- **Never report `document.documentElement.scrollHeight` as the height.** In an iframe it never returns less than the frame it is measured in, so it echoes back the current size and the frame can only grow. Measured: at frame heights 200 / 560 / 1200 / 2000 it reports 535 / 560 / 1200 / 2000 for content that is really 535. One long rejection message would leave the frame tall for the rest of the conversation. `resize()` therefore sets `height: max-content` on the root, reads `getBoundingClientRect().height`, and restores.
- **`preferredSize` is not a field.** It does not appear anywhere in the spec types; the height is whatever the view reports. `prefersBorder` *is* a field, and omitting it is what produced two nested boxes — the host drew one and the view drew another inside it. The resource asks for `prefersBorder: True` and the view draws no border, which also degrades correctly on a host that draws nothing, because the input fills carry the structure.
- **`prefersBorder` says nothing about padding, and no field does.** Observed in Codex on `4272615`: it draws the border and insets the frame by zero, so the view's text sat against the line, nearer to it than Codex's own tool label. Claude Desktop does inset, which is why the earlier "the host draws the box, so the view draws nothing" reasoning looked right and was only half right. The view now pads itself with `var(--gap-tight) var(--gap)`; on a host that already insets, the content is inset twice, which is loose but not broken — the cheaper of the two failures. `host.html`'s `chrome=tight` mode reproduces the Codex case (border, no inset) and `chrome=host` the Claude Desktop one. Body padding is inside the `max-content` measurement, so the reported height still lands with 0px dead space.
- **The `ui/initialize` result is not empty.** It carries `hostContext` with the active `theme`, a `styles.variables` palette **and** `styles.css.fonts` — the host's own `@font-face` rules, which the spec makes the *app's* job to install. It is refreshed later by a `ui/notifications/host-context-changed` notification, which has a method and no id and so matches neither branch of a listener written only for replies and host-initiated requests. All three are handled now. Dropping the font rules is the quiet failure: `--font-sans` then names a family the frame never loaded, the view renders in a substituted face, and the height it measures is measured against that face. Regression test: `test_the_view_installs_the_font_rules_the_host_hands_it`.

Colour is split deliberately: surfaces, text and borders prefer the host's tokens so the form sits inside the client's theme, while brand and semantic colours are always Delta's own (`--brand-india-*`, `--positive-*`, `--negative-*` from delta.exchange). The logo is the official mark inlined as `<svg>` with its one gradient flattened, because the test bans the syntax a gradient reference needs. Delta's Aileron typeface cannot come across — it is a web font, and fetching it hits the policy that blanks the frame.

**Type size is the host's, never the view's.** The stylesheet names no pixel type size and no width. Type comes from the `--font-text-*` / `--font-heading-*` / `--font-weight-*` tokens, and the two spacing steps — `--gap: 1em` between questions, `--gap-tight: .35em` binding a label to its control and a control to its note — are in em, so both track whatever type the host asked for. An earlier version hardcoded `14px`/`13px` type and a 3/4/6/9/12/14/16px spacing ladder tuned against that base, and that is what looked wrong in Codex, which does not run a 14px base. Measured with the host's own tokens applied: identical content reported 437px at the 16px default and 381px at a host-supplied 14px, with no rule re-tuned. Regression test: `test_the_view_names_no_type_size_of_its_own` fails on a px literal in any font declaration. Note that `font: inherit` on a control drags the body's prose line-height in with it, which leaves a single-line field standing a third taller than its text — the controls reset `line-height` immediately after, and it has to stay after or the shorthand wins.

**Spacing lives on a `.field` wrapper, one per question, not on the controls.** Putting it on the controls cannot express the mode note, which is empty most of the time: a bottom margin on the select leaves a hole when there is no note and doubles the gap when there is one.

**The controls are native, but not bare.** They keep the platform's keyboard behaviour and, for the select, a menu drawn outside the frame where the app's bounds cannot clip it. What is set on them is only what makes them belong to this form: padding in em, and colour, border and radius from `--color-background-secondary` / `--color-border-primary` / `--border-radius-md` / `--border-width-regular`, so a client's own field styling carries through. Fallbacks are `color-mix()` against the `canvas`/`canvastext` system colours rather than literals, which means they follow `color-scheme` — verified in both light and dark against a host sending no palette at all. The one pair that genuinely needs a value per scheme is `--positive` / `--negative`, which use `light-dark()` with Delta's own light and dark tones. Everything else that overrides anything is deliberate and short: the brand-filled button (a native one stops reading as the primary action), `accent-color` on the radios and checkbox, a focus ring at `outline-offset: 0` on fields so it hugs their existing border, and the two flex rows that are structural — logo beside title, checkbox opposite link.

`save_credentials` returns `account`, `path` and `next_step` as fields alongside `message` on a clean save, because the view renders its own connected state from them rather than printing the sentence. `message` stays for clients that show no view.

Those `_meta` arguments are why `pyproject.toml` floors `mcp` at 1.26 — `meta=` landed on `FastMCP.tool` in 1.19 and on `FastMCP.resource` in 1.26, and below that the decorators reject it at import.

### Trading surface (mutations)

`tools/trading.py` exposes the authenticated write tools (place/edit/cancel order, cancel-all, place/edit/cancel batch, place/edit bracket, set-leverage, change-margin, close-all, auto-topup). Its `register(mcp, client, audit)` is gated on `(cfg.has_credentials and cfg.mode == "trade")` in `build_server`; `DELTA_MCP_MODE` defaults to `read`, so the surface is off unless explicitly opted into.

### Trading is enabled per client, and that is load-bearing

`DELTA_MCP_MODE` is read **only from the process environment**, never from the shared file, because every MCP client on the machine reads that file and one value in it would arm order placement in all of them. The in-chat form can still turn trading on, because it writes a *scoped* name instead: `config.mode_key(client)` produces `DELTA_MCP_MODE_<CLIENT>` from the name the client gave in the MCP handshake, punctuation collapsed to underscores, and `config.mode_for_client(name)` resolves the environment first and that key second.

A client only identifies itself during the handshake, which happens after `build_server` has finished assembling the tool list, so the entitlement is applied at the **first `tools/list` of a session** — `build_server` wraps that request handler, arms trading before delegating, and the mutating tools appear in that very first listing rather than behind a later notification. It is decided once per session on purpose: choosing trade in the form writes the key but must not arm order placement in the session that asked for it. Regression tests: `test_trading_arms_only_for_the_client_it_was_enabled_for`, `test_choosing_trade_does_not_arm_it_in_the_session_that_chose_it`, `test_a_client_env_var_still_outranks_the_scoped_setting`.

`get_connection_status` reports `mode` (live now) and `mode_after_restart` (what this client is entitled to), and folds the difference into `restart_required` — otherwise it would report nothing outstanding while trading was still waiting, which is the contradiction the field exists to prevent.

Conventions in `trading.py`:
- Every mutating tool takes `dry_run: bool`. The shared `_finish(tool, method, path, payload, dry_run)` helper strips `None` keys, and when `dry_run` returns `{dry_run, method, path, payload}` **without** any HTTP call; otherwise it sends via `client.post/put/delete` and records to the audit log on both success and `DeltaApiError`.
- Order-level boolean flags (`post_only`, `reduce_only`, `cancel_*`) are Delta **string enums** — convert with `_bs()` to `"true"`/`"false"`. Position-level flags (`auto_topup`, `close_all_*`) are real JSON booleans.
- `close_all_positions` needs `user_id`; it is auto-resolved from `/profile` once and cached per-process in the `register` closure — never a tool param.
- Batch tools cap at `_MAX_BATCH = 50`.

### Audit logging

`audit_log.py` exposes `configure(cfg) -> AuditLog | None` (returns `None` unless `mode == "trade"`; `DELTA_MCP_AUDIT=off|false|0|no` is a kill switch). `AuditLog.record(...)` appends one JSON line per mutation to `~/.delta-exchange-mcp/audit/audit-<ts>-<pid>.log`, created `0600`. **Invariant: no credentials** — only the request body (which carries none) and a summarized result are recorded. `configure` caches a single `_INSTANCE` per process so `build_server` and `main`'s banner share one file. `server.py` registers `get_trading_status` (trade mode only) to report `{mode, audit_log_path}`. Regression test: `test_audit_records_success_and_error_without_secrets`.

### Debug logging

`debug_log.py` exposes `configure(cfg) -> Path | None`, called from `build_server`. When
`DELTA_MCP_DEBUG` is truthy it attaches a `FileHandler` to the `delta_exchange_mcp` and `httpx`
loggers (INFO, `propagate=False`, **never** `logging.basicConfig`) so request URLs + response
bodies land in `~/.delta-exchange-mcp/logs/debug-<ts>-<pid>.log`. `client.py` emits the `→`/`←`/`✗`
lines. **Invariant: credentials (api-key / api_secret / signature / timestamp) are never logged** —
only headers carry them and we never log the headers dict. Regression test:
`test_logs_request_and_body_but_no_secrets`. The module is deliberately **not** named `logging.py`
(would shadow the stdlib `logging` import). `server.py` registers a `get_debug_status` tool (only
when debug is on) so the assistant can report the log path; the path is also in the stderr startup
banner.

### Environment naming

`DELTA_MCP_ENV` values are `india_prod` / `india_testnet` (not `mainnet`/`testnet`) to match Delta's own URL naming (`api.india.delta.exchange`, `cdn-ind.testnet.deltaex.org`). `india_prod` is the default — users ask "what's BTCUSD mid", they mean prod, not testnet.

API keys are env-scoped on Delta's side: prod keys created at delta.exchange only work against `india_prod`; demo keys at demo.delta.exchange only work against `india_testnet`. Mismatch → `InvalidApiKey`.

`DELTA_MCP_MODE` is `read` (default) or `trade`; only `trade` registers `tools/trading.py`. `DELTA_MCP_AUDIT` (kill switch) and `DELTA_MCP_AUDIT_FILE` (path override) govern the audit log.

## Reference — Delta Exchange API

The upstream source of truth for endpoint shapes is the **Slate docs repo at `/Users/anuj/Documents/work/Delta/slate`**, specifically `swagger_v2.json` and `source/includes/_*.md`. When adding or fixing a tool:

```bash
jq '.paths["/products"].get.parameters' /Users/anuj/Documents/work/Delta/slate/swagger_v2.json
```

Auth spec lives at `source/includes/_authentication.md` (signing payload format, ±5 sec timestamp window, documented error codes).

## Distribution

**Local stdio only.** Each user runs the server as a subprocess of their MCP client via `uvx`:

```bash
uvx delta-exchange-mcp
```

There is intentionally **no HTTP transport, no Docker image, and no shared hosted endpoint**. Per-user API keys can't safely route through a shared HTTP server, and the financial-tool nature of this MCP means users should be able to read the code that runs against their account. If you find yourself adding `streamable-http`, `transport=` flags, or a `Dockerfile`, stop and discuss first.

## Tests

`respx` mocks httpx for unit tests (no live network). Live verification happens through `scripts/smoke.py` (Python-level) and `scripts/inspect.sh --cli` (MCP-protocol-level) — both hit real testnet/prod and are run manually, not in CI. When fixing a bug surfaced by live use, add a `respx` regression test (see `test_none_params_are_stripped_before_send` and `test_signing_payload_includes_v2_prefix` for the pattern).

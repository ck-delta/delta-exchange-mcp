#!/usr/bin/env bash
# Launch MCP Inspector against the delta-exchange-mcp stdio server.
#
# Two modes:
#
#   Web UI mode (default) — opens UI on :6274 and proxy on :6277.
#     bash scripts/inspect.sh
#   With creds:
#     DELTA_API_KEY=... DELTA_API_SECRET=... bash scripts/inspect.sh
#
#   CLI mode — headless, works over SSH (no browser needed).
#     bash scripts/inspect.sh --cli --method tools/list
#     bash scripts/inspect.sh --cli --method tools/call \
#       --tool-name get_ticker --tool-arg symbol=BTCUSD
#
# Note: the Inspector treats everything before its own flags as the server
# command. So the correct invocation is:
#   npx ... inspector [-e KEY=VAL ...] <server-cmd> [<server-args>...] [--method ...] [--cli]

set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"

# Bind to 0.0.0.0 so Tailscale clients can open the UI. Comment this out if
# you'd rather SSH port-forward (ssh -L 6274:localhost:6274 <host>).
export HOST="${HOST:-0.0.0.0}"
export CLIENT_PORT="${CLIENT_PORT:-6274}"
export SERVER_PORT="${SERVER_PORT:-6277}"

ENV_ARGS=(
  -e "DELTA_MCP_ENV=${DELTA_MCP_ENV:-testnet}"
  -e "DELTA_MCP_MODE=${DELTA_MCP_MODE:-read}"
)
if [[ -n "${DELTA_API_KEY:-}" ]]; then
  ENV_ARGS+=(-e "DELTA_API_KEY=${DELTA_API_KEY}")
fi
if [[ -n "${DELTA_API_SECRET:-}" ]]; then
  ENV_ARGS+=(-e "DELTA_API_SECRET=${DELTA_API_SECRET}")
fi

exec npx --yes @modelcontextprotocol/inspector \
  "${ENV_ARGS[@]}" \
  uv run delta-exchange-mcp \
  "$@"

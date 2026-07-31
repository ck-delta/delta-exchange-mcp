#!/usr/bin/env bash
# Build the one-click .mcpb bundle from the repo source.
#
#   bash packaging/mcpb/build.sh            # build + self-sign
#   SIGN=none bash packaging/mcpb/build.sh  # build unsigned
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"

# The published npm CLI (2.1.2, released 2025-12-04) signs bundles that Claude Desktop
# rejects: it appends the signature past the zip EOCD without updating comment_length.
# Fixed on mcpb main by PR #204 but never released. Point MCPB_CLI at a main build to
# sign — see README.
if [[ -n "${MCPB_CLI:-}" ]]; then
  MCPB="node ${MCPB_CLI}"
else
  MCPB="npx --yes @anthropic-ai/mcpb@latest"
fi
VERSION="$(grep -m1 '^version' "$REPO/pyproject.toml" | cut -d'"' -f2)"
WHEEL="delta_exchange_mcp-${VERSION}-py3-none-any.whl"

echo "==> building wheel ${VERSION}"
rm -rf "$HERE/wheels"
mkdir -p "$HERE/wheels"
uv build --wheel --out-dir "$HERE/wheels" --project "$REPO" >/dev/null

echo "==> pinning the vendored wheel"
# The caps are stated here as well as in the wheel on purpose. mcp 2.0 removed
# mcp.server.fastmcp, so an uncapped resolve yields a bundle that dies at import — and a
# wheel that ever loses its own ceiling would otherwise take the bundle down with it.
cat > "$HERE/pyproject.toml" <<TOML
[project]
name = "delta-exchange-mcp-bundle"
version = "${VERSION}"
requires-python = ">=3.12"
dependencies = [
    "delta-exchange-mcp==${VERSION}",
    "mcp>=1.12.4,<2",
    "httpx>=0.28.1,<1",
    "pydantic>=2.13.2,<3",
]

[tool.uv.sources]
delta-exchange-mcp = { path = "wheels/${WHEEL}" }
TOML

echo "==> locking"
rm -f "$HERE/uv.lock"
uv lock --directory "$HERE" >/dev/null

echo "==> generating manifest from the live tool list"
uv run --directory "$HERE" --frozen python make_manifest.py manifest.json "$VERSION"

echo "==> packing"
rm -rf "$HERE/.venv" "$HERE"/*.mcpb
cd "$HERE"
$MCPB validate manifest.json 2>&1 | grep -v '^npm notice' || true
$MCPB pack . "delta-exchange-mcp-${VERSION}.mcpb" 2>&1 | grep -v '^npm notice'

if [[ "${SIGN:-none}" == "self" ]]; then
  if [[ -z "${MCPB_CLI:-}" ]]; then
    echo "!!  refusing to sign with the published CLI — it corrupts the archive." >&2
    echo "!!  set MCPB_CLI=/path/to/mcpb/dist/cli/cli.js (a main build). See README." >&2
    exit 1
  fi
  echo "==> self-signing with the main-built CLI"
  $MCPB sign "$HERE/delta-exchange-mcp-${VERSION}.mcpb" --self-signed 2>&1 | grep -v '^npm notice'
fi

echo
echo "built: $HERE/delta-exchange-mcp-${VERSION}.mcpb"

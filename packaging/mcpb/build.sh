#!/usr/bin/env bash
# Build and verify the one-click .mcpb bundle from the repo source.
#
#   bash packaging/mcpb/build.sh
#
# Signing is separate and needs a certificate — see sign.py and the README.
# Everything shared with the published package (version, dependency ceilings, licence,
# URLs, the Python floor) is derived from the repo's pyproject.toml by make_bundle.py.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
PY=(uv run --no-project python)

VERSION="$("${PY[@]}" "$HERE/make_bundle.py" version)"
# Pinned rather than @latest: this packs the artifact we attach to a release.
MCPB=(npx --yes "@anthropic-ai/mcpb@$("${PY[@]}" "$HERE/make_bundle.py" mcpb-cli-version)")
OUT="$HERE/delta-exchange-mcp-${VERSION}.mcpb"

echo "==> building wheel ${VERSION}"
rm -rf "$HERE/wheels"
mkdir -p "$HERE/wheels"
uv build --wheel --out-dir "$HERE/wheels" --project "$REPO" >/dev/null

echo "==> generating the bundle project from the repo's metadata"
"${PY[@]}" "$HERE/make_bundle.py" pyproject

echo "==> locking"
rm -f "$HERE/uv.lock"
uv lock --directory "$HERE" >/dev/null

echo "==> generating the manifest from the live tool list"
uv run --directory "$HERE" --frozen python make_bundle.py manifest

echo "==> packing"
rm -rf "$HERE/.venv" "$HERE"/*.mcpb
cd "$HERE"
"${MCPB[@]}" validate manifest.json 2>&1 | grep -v '^npm notice' || true
"${MCPB[@]}" pack . "$OUT" 2>&1 | grep -v '^npm notice'

echo "==> verifying"
"${PY[@]}" "$HERE/verify.py" "$OUT"

echo
echo "built: $OUT"

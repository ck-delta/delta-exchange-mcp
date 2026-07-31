#!/usr/bin/env bash
# Build the mcpb CLI from a pinned upstream commit and print the path to it.
#
# The published npm release (2.1.2, 2025-12-04) signs bundles that Claude Desktop refuses:
# it appends the signature past the zip end-of-central-directory record without updating
# that record's comment-length field. Fixed upstream by PR #204 and never released — npm
# has had no publish since. So we build the fix from source rather than ship a signer we
# know produces uninstallable artifacts.
#
# Pinning a commit SHA is also the integrity control: a git SHA is a hash of the tree, so
# this is content-addressed in a way an npm version range is not.
set -euo pipefail

# modelcontextprotocol/mcpb main @ 2026-04-22. Bump deliberately, never to a moving ref.
MCPB_SHA="70fe3b34cd6dff1b3bba046638edc72a6467a4fb"
CACHE="${MCPB_CLI_CACHE:-${TMPDIR:-/tmp}/mcpb-cli}"
BUILT="$CACHE/$MCPB_SHA/dist/cli/cli.js"

if [[ ! -f "$BUILT" ]]; then
  rm -rf "$CACHE/$MCPB_SHA"
  mkdir -p "$CACHE/$MCPB_SHA"
  git -C "$CACHE/$MCPB_SHA" init -q
  git -C "$CACHE/$MCPB_SHA" remote add origin https://github.com/modelcontextprotocol/mcpb.git
  git -C "$CACHE/$MCPB_SHA" fetch -q --depth 1 origin "$MCPB_SHA"
  git -C "$CACHE/$MCPB_SHA" checkout -q FETCH_HEAD
  npm --prefix "$CACHE/$MCPB_SHA" install --silent --no-audit --no-fund >&2

  # `tsc` reports one pre-existing type error upstream (node-forge Buffer in sign.ts) but
  # still emits. Tolerate the exit code, then require the output to exist and run — if it
  # did not emit, that check fails rather than silently using a stale or missing CLI.
  npm --prefix "$CACHE/$MCPB_SHA" run build:code --silent >&2 || true
fi

if [[ ! -f "$BUILT" ]]; then
  echo "mcpb CLI failed to build at $MCPB_SHA" >&2
  exit 1
fi
node "$BUILT" --version >/dev/null 2>&1 || {
  echo "mcpb CLI built at $MCPB_SHA but does not run" >&2
  exit 1
}

echo "$BUILT"

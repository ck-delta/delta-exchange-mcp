# One-click bundle (`.mcpb`)

Packages the server so a non-technical user installs it by double-clicking a file and
typing their API key into a form, instead of hand-editing `claude_desktop_config.json`.

Bundles are supported by **Claude Desktop, Claude Code, and MCP for Windows**. Cursor,
VS Code, Codex and Windsurf do not read `.mcpb` — they keep the existing `uvx` install.

## Build

```bash
bash packaging/mcpb/build.sh            # build, unsigned

# Signing needs a CLI built from mcpb main — the npm release is too old (see Caveats):
git clone --depth 1 https://github.com/modelcontextprotocol/mcpb.git /tmp/mcpb-main
cd /tmp/mcpb-main && npm install && npm run build:code   # tsc reports one type error but emits
SIGN=self MCPB_CLI=/tmp/mcpb-main/dist/cli/cli.js bash packaging/mcpb/build.sh
```

`build.sh` refuses to sign with the published CLI rather than emit a broken artifact.

Produces `packaging/mcpb/delta-exchange-mcp-<version>.mcpb`. The version is read from the
repo's `pyproject.toml`, and the manifest's tool list comes from introspecting the server,
so the two cannot drift.

`icon.png` is the Delta Exchange mark, rendered at 512x512 from the vector source used by
`delta-exchange/api-console` (`app/favicon.svg`) with the viewBox widened to `-3 -3 36 36`
so it is not edge-to-edge at icon sizes:

```bash
rsvg-convert -w 512 -h 512 favicon.svg -o icon.png
```

`manifest.json` and `pyproject.toml` here are **generated** — they are committed so the
shipped manifest and the dependency pins are reviewable in a diff, but `build.sh` rewrites
both, so edit `make_manifest.py` and `build.sh` rather than the output. `uv.lock`,
`wheels/` and `*.mcpb` are build outputs and are not committed.

## Install to test

Double-click the `.mcpb`, or drag it onto Claude Desktop. Leave the API fields empty for
market data only.

## Decisions

**Read-only.** The manifest pins `DELTA_MCP_MODE=read`, so the bundle registers market data
plus account reads and no mutations. It is pinned rather than omitted on purpose: the client
merges the manifest's environment over the one it was launched with, so leaving the variable
out lets an ambient `DELTA_MCP_MODE=trade` register all 13 mutation tools in a bundle whose
description promises it cannot place orders.

Trading stays on the manual-config path, where the friction of editing a file is doing real
safety work — the trading tools have no notional cap, and `place_order` sizes in contracts
rather than coins.

**`server.type: "uv"`.** Needs `uv` on the machine but no other setup. The alternative,
`type: "binary"` with a PyInstaller executable, removes that prerequisite entirely but
costs four platform builds plus Apple notarization. Worth doing only if the `uv`
prerequisite proves to be where users drop off.

**Dependencies pinned and locked.** `uv.lock` ships inside the bundle and the launch line
uses `--frozen`, so the dependency tree cannot re-resolve on a user's machine.

## Caveats

- **Do not sign with the published npm CLI.** `@anthropic-ai/mcpb@2.1.2` (published
  2025-12-04) appends the PKCS#7 blob *after* the zip end-of-central-directory record but
  leaves that record's comment-length field at 0. Lenient readers (Python `zipfile`,
  `unzip`, `mcpb unpack`) skip the orphaned bytes, so the tool's own round-trip looks fine;
  Claude Desktop uses a strict reader and refuses the file with `Invalid comment length.
  Expected: 2264. Found: 0`. Reproduced with both `--self-signed` and a real CA-issued
  chain. Upstream issue
  [#278](https://github.com/modelcontextprotocol/mcpb/issues/278).

  Already fixed on mcpb `main` by
  [PR #204](https://github.com/modelcontextprotocol/mcpb/pull/204) (merged 2026-03-18),
  which sets `comment_length` when signing. It has never been released — npm has had no
  publish since 2025-12-04. Build from `main` and pass `MCPB_CLI`, as above.

  Verify any bundle before shipping it:

  ```bash
  python - <<'PY'
  import struct, pathlib
  b = pathlib.Path("delta-exchange-mcp-0.5.0.mcpb").read_bytes()
  i = b.rfind(b"PK\x05\x06")
  clen, trail = struct.unpack("<H", b[i+20:i+22])[0], len(b) - (i + 22)
  print("valid:", clen == trail)   # unsigned: 0 == 0. signed: 2264 == 2264.
  PY
  ```

- **`mcpb verify` cannot confirm any signature.** It calls node-forge's
  `PkcsSignedData.verify()`, which node-forge has never implemented — it always throws, and
  the catch-all maps that to "not signed". Affects every signature, self-signed or not.
  Upstream issues [#277](https://github.com/modelcontextprotocol/mcpb/issues/277) and
  [#21](https://github.com/modelcontextprotocol/mcpb/issues/21) (open since 2025-06-28).
  Do not gate CI on `mcpb verify`; use the zip check above instead.
- **Whether Claude Desktop supplies `uv` itself is unverified.** If it does not, the user
  still installs `uv` first, and `compatibility.runtimes.python` is what surfaces that.

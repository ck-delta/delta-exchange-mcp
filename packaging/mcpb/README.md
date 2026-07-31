# One-click bundle (`.mcpb`)

Packages the server so a non-technical user installs it by double-clicking a file and
typing their API key into a form, instead of hand-editing `claude_desktop_config.json`.

Bundles are supported by **Claude Desktop, Claude Code, and MCP for Windows**. Cursor,
VS Code, Codex and Windsurf do not read `.mcpb` — they keep the existing `uvx` install.

## Build

```bash
bash packaging/mcpb/build.sh
```

Produces and verifies `packaging/mcpb/delta-exchange-mcp-<version>.mcpb`. The same script
runs in CI on every PR that touches `packaging/mcpb/`, `src/` or `pyproject.toml`, so a
local build and a release build are the same build.

## Files

| File | |
|---|---|
| `build.sh` | Orchestration: wheel, project, lock, manifest, pack, verify. |
| `make_bundle.py` | Generates `pyproject.toml` and `manifest.json`. **Edit copy here.** |
| `verify.py` | Checks a built bundle. Run by `build.sh` and by CI. |
| `mcpb_cli.sh` | Builds the mcpb CLI from a pinned upstream commit (see Caveats). |
| `sign.py` | Signs with that CLI, then checks the archive declares the signature. |
| `manifest.json` | Generated, **committed** — the user-facing contract. CI fails if stale. |
| `pyproject.toml`, `uv.lock`, `wheels/`, `*.mcpb` | Generated, not committed. |

## Nothing shared is written twice

`make_bundle.py` reads the repo's `pyproject.toml` for everything the bundle must agree
with: name, version, licence, URLs, the Python floor, and the dependency ceilings. Restating
any of those invites the two to drift, and it has already bitten once — the bundle used to
carry its own copy of `mcp<2`, which would have silently pinned below the SDK the moment the
project raised that ceiling.

What stays literal is the copy shown to someone installing the bundle: `display_name`, the
descriptions, and the three `user_config` field labels. That is deliberately different text
from the PyPI summary, which is written for developers. The rule: if two values must move
together, derive one from the other; if they would sensibly diverge, write both.

## What `verify.py` checks

Packing successfully is not evidence the bundle works, so `build.sh` will not report success
until all of this passes:

- the archive is valid to a **strict** zip parser, which is what Claude Desktop uses
- the packed payload is **exactly** the expected file set, so build tooling sitting beside
  it in this directory cannot leak in through a missed `.mcpbignore` rule
- a real MCP **handshake** against a fresh unpack — `initialize`, then `tools/list`
- **no mutation tool registered** in that handshake

The last check is weaker than it reads and should be strengthened. The handshake starts the
server with no credentials in the environment, and the mutation tools are gated on credentials
*and* `DELTA_MCP_MODE=trade`, so they could not have registered whichever mode was set. It
reports 14 tools and 0 mutating; a real install with a key reports 27 and 0. To make it a
genuine test the handshake has to start from a hostile environment — credentials present,
`DELTA_MCP_MODE=trade` — with the manifest's `env` applied over it the way a host does. That
version fails if the pin below is ever dropped. This one cannot.

## The icon

`icon.png` is the Delta Exchange mark at 512x512, rendered from the vector source used by
`delta-exchange/api-console` (`app/favicon.svg`) with the viewBox widened to `-3 -3 36 36`
so it is not edge-to-edge at icon sizes:

```bash
rsvg-convert -w 512 -h 512 favicon.svg -o icon.png
```

## Install to test

Double-click the `.mcpb`, or drag it onto Claude Desktop. Leave the API fields empty for
market data only.

The first install of any `uv` bundle needs network and can be slow: the host resolves `uv`,
then runs `uv sync`, which fetches a Python interpreter and the dependencies. It surfaces
that as download progress.

The extension lands in `~/Library/Application Support/Claude/Claude Extensions/`, one
directory per extension, with the `.venv` that `uv sync` built alongside the shipped payload.
That directory and the app's own log are where to look when a bundle installs but will not
start.

## Decisions

**Read-only.** The manifest pins `DELTA_MCP_MODE=read`, so the bundle registers market data
plus account reads and no mutations. It is pinned rather than omitted deliberately. If a host
merges the manifest's environment over the one it was launched with, which is the substitution
model the spec describes, then omitting the variable lets an ambient `DELTA_MCP_MODE=trade`
register all 13 mutation tools in a bundle whose description promises it cannot place orders.
Pinning costs nothing and does not depend on knowing which way any particular host resolves
that, so it holds either way.

Trading stays on the manual-config path, where the friction of editing a file is doing real
safety work — the trading tools have no notional cap, and `place_order` sizes in contracts
rather than coins.

**`server.type: "uv"`.** No prerequisite on the user's machine — not `uv`, and not Python.
Claude Desktop resolves `uv` in three steps: it looks for a system installation, else reuses
a copy it downloaded earlier under `uv-runtime/`, else downloads one from the `astral-sh/uv`
releases and clears the macOS quarantine attribute. It then runs `uv sync` against the
`pyproject.toml` and `uv.lock` shipped inside the bundle, letting `uv` fetch an interpreter
meeting the `>=3.12` floor rather than requiring a system Python. Where the manifest says
`"command": "uv"` the app discards that string and launches whichever binary it resolved, by
absolute path — so nothing resolves against the user's `PATH` at launch, which matters
because an app started from Finder inherits the launchd environment rather than a shell one.

That removes the reason to consider `type: "binary"` with a PyInstaller executable. That
option existed only to drop a `uv` prerequisite which turns out not to exist, and it would
have cost four platform builds plus Apple notarization.

**Dependencies pinned and locked.** `uv.lock` ships inside the bundle and the launch line
passes `--frozen`, so nothing re-resolves at start-up. The `uv sync` the host runs at install
time is a separate step and is not `--frozen`, but it consumes that same shipped lock, which
is generated alongside the shipped `pyproject.toml` and so agrees with it.

## Caveats

- **Signing uses a CLI built from upstream, not the npm release.** The published
  `@anthropic-ai/mcpb` (2.1.2, 2025-12-04) appends the PKCS#7 blob past the zip
  end-of-central-directory record but leaves that record's comment-length field at 0.
  Lenient readers (Python `zipfile`, `unzip`) skip the orphaned bytes; Claude Desktop uses
  a strict reader and refuses the file with `Invalid comment length`. Reproduced with both
  `--self-signed` and a real CA-issued chain. Upstream issue
  [#278](https://github.com/modelcontextprotocol/mcpb/issues/278), fixed by
  [PR #204](https://github.com/modelcontextprotocol/mcpb/pull/204) (merged 2026-03-18) and
  never released — npm has had no publish since 2025-12-04.

  `mcpb_cli.sh` therefore builds the CLI from a pinned upstream commit that carries the
  fix, and `build.sh` and `sign.py` both use that. Bump the SHA deliberately; never point
  it at a moving ref.

  The pin covers the dependencies too. Upstream vendors its own yarn release at
  `.yarn/releases/` and commits `yarn.lock`, so installing with that binary and
  `--immutable` fixes all 605 transitive packages to the same commit. Do not substitute
  `npm install` — it ignores a yarn lockfile and resolves the tree fresh at build time,
  which is the code that then handles the signing certificate and private key.

  ```bash
  uv run --no-project python packaging/mcpb/sign.py <bundle.mcpb> cert.pem key.pem [chain.pem]
  uv run --no-project python packaging/mcpb/verify.py <bundle.mcpb>
  ```

  Two traps worth knowing. The built CLI still reports `--version` 2.1.2, because upstream
  never bumped main, so the version string tells you nothing about whether the fix is
  present — `sign.py` checks the archive structure instead. And `tsc` reports one
  pre-existing type error upstream while still emitting; `mcpb_cli.sh` tolerates the exit
  code and then requires the binary to exist and run.

  Signing is not wired into CI: it needs a real certificate, which we do not have yet. When
  one exists, add `MCPB_SIGNING_CERT` / `MCPB_SIGNING_KEY` as repository secrets and a
  signing step to `bundle.yml` before the upload.

- **`mcpb verify` cannot confirm any signature.** It calls node-forge's
  `PkcsSignedData.verify()`, which node-forge has never implemented — it always throws, and
  the catch-all maps that to "not signed". Affects every signature, self-signed or not.
  Upstream issues [#277](https://github.com/modelcontextprotocol/mcpb/issues/277) and
  [#21](https://github.com/modelcontextprotocol/mcpb/issues/21) (open since 2025-06-28).
  Never gate CI on `mcpb verify`; `verify.py` is the structural check that actually works.
- **Only Claude Desktop's `uv` provisioning is confirmed, and only its discovery branch.**
  A real install on macOS (2026-07-31, app build 2026-07-24) logged `[UV Runtime] Running uv
  sync`, then `[UV Discovery] ✓ Found system UV: /opt/homebrew/bin/uv`, then `[MCP Launch]
  [UV Runtime] Launching: /opt/homebrew/bin/uv`, and produced a `.venv` on a `uv`-downloaded
  CPython 3.13.13 rather than a system one — so the no-Python-prerequisite claim is observed,
  not inferred. The download fallback is read from the app bundle (a per-platform table of
  `astral-sh/uv` release URLs behind the discovery step) and has **not** been exercised here,
  because this machine already had `uv`. To test it, remove `uv` from where the app searches
  and reinstall. Claude Code and MCP for Windows also accept `.mcpb`, but whether they
  provision `uv` the same way is unverified, and `compatibility.runtimes.python` is what
  surfaces the requirement if one of them does not.

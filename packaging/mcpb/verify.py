"""Check a built .mcpb: archive structure, then a real MCP handshake from a fresh unpack.

Packing successfully is not evidence the bundle works. This unpacks the artifact the way a
client would and speaks the protocol to it, so a bundle that installs but cannot start
fails here rather than on someone's machine.
"""

import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

MUTATION_PREFIXES = (
    "place_",
    "cancel_",
    "edit_",
    "close_",
    "adjust_",
    "set_product",
    "configure_",
)


def check_archive(mcpb: Path) -> None:
    """Trailing bytes must be declared in the EOCD comment length or strict readers refuse.

    Claude Desktop uses a strict zip parser. A signature appended past the end-of-central-
    directory record without updating that field yields "Invalid comment length" at install,
    while lenient readers (Python, Info-ZIP) open the same file happily.
    """
    raw = mcpb.read_bytes()
    eocd = raw.rfind(b"PK\x05\x06")
    if eocd == -1:
        raise SystemExit("not a zip: no end-of-central-directory record")
    declared = struct.unpack("<H", raw[eocd + 20 : eocd + 22])[0]
    trailing = len(raw) - (eocd + 22)
    if declared != trailing:
        raise SystemExit(
            f"archive is not strict-parser valid: EOCD declares a {declared}-byte comment "
            f"but {trailing} bytes follow it"
        )

    with zipfile.ZipFile(mcpb) as z:
        bad = z.testzip()
        if bad is not None:
            raise SystemExit(f"corrupt entry: {bad}")
        names = set(z.namelist())

    # Assert the payload rather than trusting .mcpbignore. Build tooling sits beside the
    # payload in this directory, so one missed ignore rule would otherwise ship it silently.
    required = {"manifest.json", "pyproject.toml", "uv.lock", "icon.png", "server/main.py"}
    missing = required - names
    if missing:
        raise SystemExit(f"missing from the bundle: {', '.join(sorted(missing))}")

    wheels = {n for n in names if n.startswith("wheels/") and n.endswith(".whl")}
    if len(wheels) != 1:
        raise SystemExit(f"expected exactly one vendored wheel, found {len(wheels)}")

    unexpected = names - required - wheels
    if unexpected:
        raise SystemExit(
            "unexpected files in the bundle (build tooling leaking through "
            f".mcpbignore?): {', '.join(sorted(unexpected))}"
        )

    print(f"  archive: {len(raw)} bytes, {len(names)} entries, CRCs OK, strict-parser valid")
    print(f"  payload: {', '.join(sorted(required))}, {wheels.pop()}")


def launch_env(manifest: dict, mode: str, config_file: Path) -> dict[str, str]:
    """The environment a host would build, over a deliberately hostile one.

    The ambient half sets DELTA_MCP_MODE=trade and supplies credentials, which is what a
    machine with those exported looks like. The manifest half is then applied on top with
    ${user_config.x} resolved the way the host resolves it. Checking the result is what
    makes "the form decides the mode, not the environment" an actual test rather than an
    assertion that passes because no credentials were present.

    The shared settings file is redirected into the throwaway unpack directory. The
    server reads ~/.delta-exchange-mcp/config.env for anything the manifest does not
    declare, and the manifest declares only mode, environment and the two credentials —
    so a developer with DELTA_MCP_DEBUG=1 in their own file would register a debug tool
    that is not in the manifest and fail the undeclared-tool check here but not in CI.
    Redirecting also keeps a build from writing into the user's home directory.
    """
    config = {k: v.get("default", "") for k, v in manifest["user_config"].items()}
    config.update({"mode": mode, "api_key": "placeholder", "api_secret": "placeholder"})

    env = dict(os.environ)
    env.update({
        "DELTA_MCP_MODE": "trade",
        "DELTA_API_KEY": "ambient",
        "DELTA_API_SECRET": "ambient",
        "DELTA_MCP_CONFIG_FILE": str(config_file),
    })
    for key, raw in manifest["server"]["mcp_config"]["env"].items():
        env[key] = re.sub(
            r"\$\{user_config\.(\w+)\}", lambda m: str(config.get(m.group(1), "")), raw
        )
    return env


def handshake(
    extracted: Path, env: dict[str, str] | None = None, timeout: float = 240.0
) -> list[str]:
    """Start the unpacked server over stdio and return the tool names it registers."""
    proc = subprocess.Popen(
        ["uv", "run", "--directory", str(extracted), "--frozen", "python", "server/main.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=env,
    )

    def send(msg: dict) -> None:
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()

    send(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "bundle-verify", "version": "1"},
            },
        }
    )

    deadline = time.time() + timeout
    seen: dict[int, dict] = {}
    asked = False
    while time.time() < deadline and 2 not in seen:
        line = proc.stdout.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(msg.get("id"), int):
            seen[msg["id"]] = msg
        if msg.get("id") == 1 and not asked:
            asked = True
            send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})

    proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()

    if 1 not in seen:
        raise SystemExit(f"no initialize response\nstderr:\n{proc.stderr.read()[-2000:]}")
    if 2 not in seen:
        raise SystemExit(f"no tools/list response\nstderr:\n{proc.stderr.read()[-2000:]}")

    info = seen[1]["result"].get("serverInfo", {})
    print(f"  handshake: initialize OK, serverInfo={info}")
    return sorted(t["name"] for t in seen[2]["result"]["tools"])


def main() -> None:
    mcpb = Path(sys.argv[1]).resolve()
    print(f"verifying {mcpb.name}")
    check_archive(mcpb)

    tmp = Path(tempfile.mkdtemp(prefix="mcpb-verify-"))
    try:
        with zipfile.ZipFile(mcpb) as z:
            z.extractall(tmp)
        manifest = json.loads((tmp / "manifest.json").read_text())

        # Someone who accepted the form's defaults, on a machine whose environment is
        # already asking for trade mode. The declared default has to win.
        shared = tmp / "shared-config.env"
        default = handshake(
            tmp, launch_env(manifest, manifest["user_config"]["mode"]["default"], shared)
        )
        leaked = [n for n in default if n.startswith(MUTATION_PREFIXES)]
        print(f"  default mode: {len(default)} tools, {len(leaked)} mutating")
        if leaked:
            raise SystemExit(
                "the default install can mutate: an ambient DELTA_MCP_MODE=trade reached "
                f"the server and registered {', '.join(leaked[:5])}"
            )
        if not default:
            raise SystemExit("no tools registered")

        # And the opt-in has to actually reach trading, or the field is decorative.
        opted = handshake(tmp, launch_env(manifest, "trade", shared))
        mutating = [n for n in opted if n.startswith(MUTATION_PREFIXES)]
        print(f"  mode=trade:   {len(opted)} tools, {len(mutating)} mutating")
        if not mutating:
            raise SystemExit("opting into trade registered no mutation tools")

        # tools_generated is false, which promises the manifest lists everything reachable.
        declared = {t["name"] for t in manifest["tools"]}
        undeclared = set(opted) - declared
        if undeclared:
            raise SystemExit(
                "manifest declares tools_generated=false but the server registers "
                f"undeclared tools: {', '.join(sorted(undeclared)[:5])}"
            )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("  OK")


if __name__ == "__main__":
    main()

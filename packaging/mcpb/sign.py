"""Sign a .mcpb with the published CLI, then declare the signature in the archive itself.

`mcpb sign` appends its signature block (`MCPB_SIG_V1` + length + PKCS#7 + `MCPB_SIG_END`)
past the zip end-of-central-directory record, but leaves that record's comment-length field
at zero. The result is not a strictly valid zip: lenient readers skip the orphaned bytes,
while Claude Desktop's strict reader refuses the file with "Invalid comment length".

Upstream fixed this on `mcpb` main in PR #204, which has never been released — the npm
package has had no publish since 2025-12-04. Rather than build an unreleased branch of
someone else's tool in order to sign a release artifact, sign with the published CLI and
then set the two-byte field here. The signature block is untouched; `extractSignatureBlock`
scans backwards for the footer magic and never reads this field.

    https://github.com/modelcontextprotocol/mcpb/issues/278
"""

import struct
import subprocess
import sys
from pathlib import Path

from make_bundle import MCPB_CLI_VERSION

SIG_HEADER = b"MCPB_SIG_V1"
EOCD_MAGIC = b"PK\x05\x06"
EOCD_COMMENT_LEN_OFFSET = 20
EOCD_FIXED_SIZE = 22


def declare_trailing_bytes(mcpb: Path) -> int:
    """Set the EOCD comment length to cover everything appended after it."""
    raw = bytearray(mcpb.read_bytes())

    # Search for the EOCD *before* the signature block: the PKCS#7 payload is arbitrary
    # bytes and could otherwise contain a false end-of-central-directory magic.
    sig = raw.rfind(SIG_HEADER)
    eocd = raw.rfind(EOCD_MAGIC, 0, sig if sig != -1 else len(raw))
    if eocd == -1:
        raise SystemExit("no end-of-central-directory record found")

    trailing = len(raw) - (eocd + EOCD_FIXED_SIZE)
    if trailing == 0:
        raise SystemExit("nothing was appended — did signing run?")
    if trailing > 0xFFFF:
        raise SystemExit(f"signature block is {trailing} bytes, too large for a zip comment")

    struct.pack_into("<H", raw, eocd + EOCD_COMMENT_LEN_OFFSET, trailing)
    mcpb.write_bytes(raw)
    return trailing


def main() -> None:
    mcpb = Path(sys.argv[1]).resolve()
    cert, key = sys.argv[2], sys.argv[3]
    intermediate = sys.argv[4] if len(sys.argv) > 4 else None

    cmd = ["npx", "--yes", f"@anthropic-ai/mcpb@{MCPB_CLI_VERSION}", "sign", str(mcpb),
           "--cert", cert, "--key", key]
    if intermediate:
        cmd += ["--intermediate", intermediate]
    subprocess.run(cmd, check=True)

    declared = declare_trailing_bytes(mcpb)
    print(f"  declared {declared}-byte signature block in the archive comment length")
    print("  note: `mcpb verify` cannot confirm this — node-forge never implemented")
    print("        PKCS#7 verification. Use verify.py for the structural check.")


if __name__ == "__main__":
    main()

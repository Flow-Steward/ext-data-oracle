"""Record pinned native build inputs and both ELF output digests."""

import hashlib
import json
from pathlib import Path
from typing import Any

r = Path(__file__).resolve().parents[1]
p = "scripts/patches/0001-flowsteward-oracle-safety.patch"
result: dict[str, Any] = {
    "tag": "v1.3.0",
    "commit": "b0010060a939455d91e4f8ba62dc3e72b1892469",
    "go_image": "golang:1.26.10-bookworm@sha256:5de7c99eb78ca5e515a4c340235d0955ec5964a5071c492c15503d7c267da473",
    "source_date_epoch": 1779400183,
    "patch": p,
    "patch_sha256": hashlib.sha256((r / p).read_bytes()).hexdigest(),
    "driver": {
        "module": "github.com/sijms/go-ora/v2",
        "version": "v2.9.0",
        "module_sum": "h1:+iQbUeTeCOFMb5BsOMgUhV8KWyrv9yjKpcK4x7+MFrg=",
        "mode": "pure-Go; OCI disabled",
    },
    "packages": [
        "github.com/googleapis/mcp-toolbox/internal/sources/oracle",
        "github.com/googleapis/mcp-toolbox/internal/tools/oracle/oraclesql",
    ],
    "binaries": {},
}
for target in ("linux-amd64", "linux-arm64"):
    b = (r / "bin" / target / "toolbox").read_bytes()
    result["binaries"][target] = {"sha256": hashlib.sha256(b).hexdigest(), "size": len(b)}
(r / "toolbox-provenance.json").write_text(json.dumps(result, indent=2) + "\n")

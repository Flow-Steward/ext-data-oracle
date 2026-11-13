import hashlib
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_actual_native_artifacts_and_provenance():
    p = json.loads((ROOT / "toolbox-provenance.json").read_text())
    assert p["commit"] == "45ed205cc8682ed066c82e0b65bcd0e8fc3becce"
    assert p["driver"]["version"] == "v3.0.1"
    assert hashlib.sha256((ROOT / p["patch"]).read_bytes()).hexdigest() == p["patch_sha256"]
    assert p["packages"] == [
        "github.com/googleapis/mcp-toolbox/internal/sources/oracle",
        "github.com/googleapis/mcp-toolbox/internal/tools/oracle/oraclesql",
    ]
    for target, machine in [("linux-amd64", 62), ("linux-arm64", 183)]:
        b = (ROOT / "bin" / target / "toolbox").read_bytes()
        assert b[:6] == b"\x7fELF\x02\x01"
        assert struct.unpack_from("<H", b, 18)[0] == machine
        assert hashlib.sha256(b).hexdigest() == p["binaries"][target]["sha256"]
        assert len(b) == p["binaries"][target]["size"]


def test_source_patch_controls_driver_and_read_bounds():
    p = (ROOT / "scripts/patches/0001-flowsteward-oracle-safety.patch").read_text()
    added = "\n".join(s[1:] for s in p.splitlines() if s.startswith("+"))
    assert "connector.Dialer(&pinnedDialer" in added
    assert "connector.WithTLSConfig" in added
    assert "tls.VersionTLS12" in added
    assert "conn.ExecContext" in added
    assert "WHERE ROWNUM <= " in added
    assert "UseNumber()" in added
    assert "470*1024" in added


def test_native_version_runs_without_network():
    import subprocess
    import toolbox

    completed = subprocess.run(
        [toolbox._binary(), "--version"], capture_output=True, timeout=10, check=False
    )
    assert completed.returncode == 0
    assert b"flowsteward.oracle" in completed.stdout + completed.stderr


def test_ci_source_build_does_not_track_generated_native_binaries():
    """A native rebuild must preserve the release validator's clean source index."""
    import subprocess

    tracked = subprocess.check_output(
        ["git", "-C", str(ROOT), "ls-files", "--", "bin/"], text=True
    ).splitlines()
    assert tracked == [], f"CI-generated native binaries must be untracked: {tracked}"
    for target in ("linux-amd64", "linux-arm64"):
        result = subprocess.run(
            ["git", "-C", str(ROOT), "check-ignore", "--", f"bin/{target}/toolbox"],
            check=False,
            capture_output=True,
        )
        assert result.returncode == 0, f"Generated native target must be ignored: {target}"

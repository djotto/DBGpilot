"""Reproduce the optional-engine investigation without adding a dependency.

Only the pinned Python candidate is downloaded/launched. Tcl and Ruby protocol
and licensing dispositions are documented in docs/protocol-review.md.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
from urllib.request import urlopen

COMMIT = "aa277c0055dffb597777bba49d4eb65d30af02a0"
SHA256 = "be699d79e4e1a4885972b4628aa3a9db863d350ab385d3fca935f3e29dcd7a6e"
URL = f"https://codeload.github.com/agroszer/komodo-python3-dbgp/tar.gz/{COMMIT}"


def investigate(cache):
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / f"{COMMIT}.tar.gz"
    if not archive.exists():
        with urlopen(URL, timeout=30) as response:
            data = response.read(32 * 1024 * 1024 + 1)
        if len(data) > 32 * 1024 * 1024:
            raise ValueError("Engine archive exceeds the investigation size limit")
        if hashlib.sha256(data).hexdigest() != SHA256:
            raise ValueError("Engine archive checksum mismatch")
        archive.write_bytes(data)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise ValueError("Cached engine archive checksum mismatch")
    with tarfile.open(archive) as source:
        source.extractall(cache, filter="data")
    root = cache / f"komodo-python3-dbgp-{COMMIT}"
    setup = (root / "setup.py").read_text()
    client = (root / "dbgp/client.py").read_text()
    # The license file contains legacy Latin-1 copyright text.
    license = (root / "LICENSE.txt").read_text(encoding="latin-1")
    launcher = (root / "bin/pydbgp").read_text()
    result = subprocess.run([sys.executable, str(root / "bin/pydbgp"), "--help"],
                            capture_output=True, text=True, timeout=10)
    return {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "candidate": "komodo-python3-dbgp", "commit": COMMIT, "archive": URL, "sha256": SHA256,
        "engine_version": re.search(r"version='([^']+)'", setup).group(1),
        "python": sys.version, "python_executable": sys.executable,
        "python_component_license_declared_mit": "Python Remote Debugging component is covered by the MIT" in license,
        "launcher_mit_header": "The MIT License" in launcher,
        "source_handlers": {command: bool(re.search(r"def do_" + command + r"\(", client))
                            for command in ("stdin", "interact", "expr", "exec", "spawnpoint_set")},
        "launch_returncode": result.returncode,
        "launch_stdout_tail": result.stdout[-2000:], "launch_stderr_tail": result.stderr[-3000:],
        "positive_live_commands_verified": [],
        "disposition": "Investigation only; no successful debugger session or live optional-command claim.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=Path(tempfile.gettempdir()) / "dbgpilot-optional-engines")
    parser.add_argument("--output", type=Path, default=Path("test-results/optional-engines.json"))
    args = parser.parse_args()
    report = investigate(args.cache)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"candidate": report["candidate"], "engine_version": report["engine_version"],
                      "launch_returncode": report["launch_returncode"], "report": str(args.output),
                      "positive_live_commands_verified": []}))


if __name__ == "__main__":
    main()

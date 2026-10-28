"""Upload a validated candidate to a GitHub testing release using gh."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def candidate_assets(candidate):
    report = json.loads((candidate / "validation.json").read_text())
    if report["status"] != "validated-unpublished-candidate":
        raise ValueError("Choose a successfully validated candidate")
    required = ("metadata_and_lock", "archive_contents", "byte_reproducible",
                "wheel_fresh_install_and_roundtrip", "sdist_fresh_install_and_roundtrip")
    if not all(report["checks"].get(name) is True for name in required):
        raise ValueError("Candidate is missing required packaging/install checks")
    if sha256(candidate / "source-manifest.json") != report["source_manifest_sha256"]:
        raise ValueError("Candidate source manifest checksum mismatch")
    version = report["version"]
    names = (f"dbgpilot-{version}-py3-none-any.whl", f"dbgpilot-{version}.tar.gz")
    if set(report["artifacts"]) != set(names):
        raise ValueError("Candidate must contain exactly the validated wheel and source archive")
    for name in names:
        path = candidate / name
        if path.resolve().parent != candidate or not path.is_file():
            raise ValueError(f"Invalid candidate artifact: {name}")
        expected = report["artifacts"][name]
        if sha256(path) != expected["sha256"] or path.stat().st_size != expected["bytes"]:
            raise ValueError(f"Artifact checksum/size mismatch: {name}")
    sums = "".join(f"{report['artifacts'][name]['sha256']}  {name}\n" for name in sorted(names))
    if (candidate / "SHA256SUMS").read_text() != sums:
        raise ValueError("SHA256SUMS differs from the validated artifact hashes")
    return report, [candidate / name for name in (*names, "SHA256SUMS")]


def origin_repository():
    remote = subprocess.check_output(["git", "remote", "get-url", "origin"], cwd=ROOT, text=True).strip()
    for prefix in ("git@github.com:", "https://github.com/", "ssh://git@github.com/"):
        if remote.startswith(prefix):
            return remote.removeprefix(prefix).rstrip("/").removesuffix(".git")
    raise ValueError("Pass --repo OWNER/REPOSITORY for this origin URL")


def release_notes(report, repository, tag, candidate):
    version = report["version"]
    wheel = f"dbgpilot-{version}-py3-none-any.whl"
    base = f"https://github.com/{repository}"
    tag_path = quote(tag, safe="")
    wheel_url = f"{base}/releases/download/{tag_path}/{wheel}"
    checksum = report["artifacts"][wheel]["sha256"]
    suite = report.get("full_suite")
    tests = f"Full-suite evidence: {suite['tests']} tests." if suite else "Full-suite evidence was not supplied; wider testing is manual."
    return f"""DBGpilot {version} testing candidate: `{candidate.name}`.

Requires Python 3.12 or 3.13. Browser debugging uses async Playwright; PHP needs Xdebug.

Install the wheel into your project's Python environment:

```sh
python -m pip install '{wheel_url}#sha256={checksum}'
```

For a private repository, download the wheel while signed in, then install that local file.

Follow the [consumer quickstart]({base}/blob/{tag_path}/docs/consumer-quickstart.md).
The attached source archive also contains that guide and `examples/consumer/`.
The wheel includes the library, CLI and opt-in pytest plugin; install browser/test tools separately.

Packaging checks passed: repeatable builds, archive contents, fresh wheel/source installs,
and installed HTTP/TCP reconnect probes. {tests}

Download `SHA256SUMS` to verify both artifacts. This is a GitHub prerelease; no PyPI upload is involved.
"""


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path, help="Directory printed by scripts/release.sh")
    parser.add_argument("--tag", required=True, help="Existing pushed tag matching the candidate's source")
    parser.add_argument("--repo", help="OWNER/REPOSITORY (default: this checkout's GitHub origin)")
    parser.add_argument("--dry-run", action="store_true", help="Validate files and preview notes without contacting GitHub")
    parser.add_argument("--publish", action="store_true", help="Publish the prerelease immediately (default: draft)")
    args = parser.parse_args(argv)
    try:
        candidate = args.candidate.resolve(strict=True)
        report, assets = candidate_assets(candidate)
        repository = args.repo or origin_repository()
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("Repository must be OWNER/REPOSITORY on github.com")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", args.tag):
            raise ValueError("Use a tag starting with a letter or digit")
        notes = release_notes(report, repository, args.tag, candidate)
        notes_path = candidate / "GITHUB_RELEASE_NOTES.md"
        command = ["gh", "release", "create", args.tag, "--repo", repository,
                   "--verify-tag", "--prerelease", "--latest=false",
                   "--title", f"DBGpilot {report['version']} ({args.tag})",
                   "--notes-file", str(notes_path)]
        if not args.publish:
            command.append("--draft")
        command.extend(str(path) for path in assets)
        if args.dry_run:
            print(notes)
            print("Upload command (not executed):\n" + shlex.join(command))
            return
        notes_path.write_text(notes)
        subprocess.run(command, cwd=ROOT, check=True)
    except (ValueError, KeyError, TypeError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"GitHub release failed: {error}\n")


if __name__ == "__main__":
    main()

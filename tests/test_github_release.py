"""Publication previews and artifact integrity without contacting GitHub."""

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("github_release", ROOT / "scripts/github_release.py")
uploader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(uploader)


@pytest.fixture
def candidate(tmp_path):
    artifacts = {}
    for name in ("dbgpilot-0.1.0-py3-none-any.whl", "dbgpilot-0.1.0.tar.gz"):
        data = name.encode()
        (tmp_path / name).write_bytes(data)
        artifacts[name] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    manifest = b"{}\n"
    (tmp_path / "source-manifest.json").write_bytes(manifest)
    report = {
        "status": "validated-unpublished-candidate", "version": "0.1.0",
        "source_manifest_sha256": hashlib.sha256(manifest).hexdigest(),
        "artifacts": artifacts,
        "checks": {name: True for name in (
            "metadata_and_lock", "archive_contents", "byte_reproducible",
            "wheel_fresh_install_and_roundtrip", "sdist_fresh_install_and_roundtrip",
        )},
    }
    (tmp_path / "validation.json").write_text(json.dumps(report))
    (tmp_path / "SHA256SUMS").write_text("".join(
        f"{artifacts[name]['sha256']}  {name}\n" for name in sorted(artifacts)
    ))
    return tmp_path


def arguments(candidate):
    return [str(candidate), "--tag", "v0.1.0-testing.1", "--repo", "example/DBGpilot"]


def forbid_upload(*args, **kwargs):
    pytest.fail("GitHub must not be invoked")


def test_dry_run_is_local_and_does_not_write_notes(candidate, monkeypatch, capsys):
    monkeypatch.setattr(uploader.subprocess, "run", forbid_upload)
    uploader.main([*arguments(candidate), "--dry-run"])
    output = capsys.readouterr().out
    assert "https://github.com/example/DBGpilot/releases/download/v0.1.0-testing.1/" in output
    assert "#sha256=" in output and "--draft" in output
    assert "Full-suite evidence was not supplied" in output
    assert not (candidate / "GITHUB_RELEASE_NOTES.md").exists()


@pytest.mark.parametrize("name", ["dbgpilot-0.1.0-py3-none-any.whl", "SHA256SUMS", "source-manifest.json"])
def test_tampered_candidate_never_reaches_github(candidate, monkeypatch, capsys, name):
    monkeypatch.setattr(uploader.subprocess, "run", forbid_upload)
    (candidate / name).write_text("tampered")
    with pytest.raises(SystemExit) as caught:
        uploader.main(arguments(candidate))
    assert caught.value.code == 1
    assert "checksum" in capsys.readouterr().err.lower() or name == "SHA256SUMS"
    assert not (candidate / "GITHUB_RELEASE_NOTES.md").exists()


@pytest.mark.parametrize("publish", [False, True])
def test_upload_requires_pushed_tag_and_only_sends_three_verified_assets(candidate, monkeypatch, publish):
    calls = []

    def record(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(uploader.subprocess, "run", record)
    uploader.main([*arguments(candidate), *(["--publish"] if publish else [])])
    assert len(calls) == 1
    command = calls[0]
    assert command[:3] == ["gh", "release", "create"]
    assert "--verify-tag" in command and "--prerelease" in command and "--latest=false" in command
    assert ("--draft" in command) is not publish
    assert command[-3:] == [str(candidate / name) for name in (
        "dbgpilot-0.1.0-py3-none-any.whl", "dbgpilot-0.1.0.tar.gz", "SHA256SUMS",
    )]
    assert (candidate / "GITHUB_RELEASE_NOTES.md").is_file()


def test_failed_validation_is_not_uploadable(candidate, monkeypatch):
    monkeypatch.setattr(uploader.subprocess, "run", forbid_upload)
    report_path = candidate / "validation.json"
    report = json.loads(report_path.read_text())
    report["status"] = "failed"
    report_path.write_text(json.dumps(report))
    with pytest.raises(SystemExit) as caught:
        uploader.main(arguments(candidate))
    assert caught.value.code == 1

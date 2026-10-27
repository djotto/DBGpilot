"""Release contract checks and rejection of accidental distribution payloads."""

import hashlib
import importlib.util
from pathlib import Path
import tomllib
import zipfile

import pytest

from dbgpilot import Server, __version__
from dbgpilot.cli import main

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("distribution_validator", ROOT / "scripts/check_distribution.py")
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


def test_source_package_cli_and_health_versions_agree(capsys):
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert project["version"] == __version__
    with pytest.raises(SystemExit) as caught:
        main(["--version"])
    assert caught.value.code == 0
    assert capsys.readouterr().out.strip() == f"dbgpilot {__version__}"
    health = Server(port=0, xdebug_port=0).health()
    assert health["version"] == __version__ and health["protocol"] == "dbgpilot/1"


def test_distribution_metadata_rejects_runtime_dependency():
    raw = b"Name: dbgpilot\nVersion: 0.1.0\nLicense: MIT\nRequires-Python: >=3.12,<3.14\nRequires-Dist: unexpected-library\n\n"
    with pytest.raises(validator.ValidationError, match="runtime dependencies"):
        validator.metadata(raw, "0.1.0", ">=3.12,<3.14")


def test_distribution_rejects_php_vendor_payload(tmp_path):
    wheel = tmp_path / "bad.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("fixtures/drupal11/vendor/leak.php", b"<?php")
    project = {"version": "0.1.0", "requires-python": ">=3.12,<3.14"}
    with pytest.raises(validator.ValidationError, match="Unexpected wheel payload"):
        validator.inspect_wheel(wheel, project, {}, tmp_path)


def test_distribution_rejects_missing_typing_marker(tmp_path):
    wheel = tmp_path / "bad.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("dbgpilot/__init__.py", b"")
    manifest = {"src/dbgpilot/__init__.py": hashlib.sha256(b"").hexdigest()}
    project = {"version": "0.1.0", "requires-python": ">=3.12,<3.14"}
    with pytest.raises(validator.ValidationError, match="Typing marker"):
        validator.inspect_wheel(wheel, project, manifest, tmp_path)


def test_distribution_refuses_archive_traversal():
    with pytest.raises(validator.ValidationError, match="Unsafe archive member"):
        validator.safe_name("../outside.py")


@pytest.mark.parametrize("kind", ["file", "directory"])
def test_clean_export_does_not_follow_source_symlinks(tmp_path, kind):
    source = tmp_path / "source"
    source.mkdir()
    for name in validator.ROOT_FILES:
        (source / name).write_text("fixture")
    package = source / "src/dbgpilot"
    if kind == "file":
        package.mkdir(parents=True)
        outside = tmp_path / "outside.py"
        outside.write_text("do not export")
        (package / "leak.py").symlink_to(outside)
    else:
        package.parent.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "leak.py").write_text("do not export")
        package.symlink_to(outside, target_is_directory=True)
    with pytest.raises(validator.ValidationError, match="symlink"):
        validator.export_source(source, tmp_path / "exported", 315532800)


def test_distribution_rejects_junit_aggregate_errors(tmp_path):
    path = tmp_path / "results.xml"
    path.write_text('<testsuite tests="1" errors="1"><testcase name="partial"/></testsuite>')
    with pytest.raises(validator.ValidationError, match="reports failures"):
        validator.suite_evidence(path)


def test_fast_only_junit_is_not_full_release_evidence(tmp_path):
    path = tmp_path / "results.xml"
    path.write_text('<testsuite tests="1"><testcase classname="tests.test_protocol" name="ok"/></testsuite>')
    with pytest.raises(validator.ValidationError, match="missing required"):
        validator.suite_evidence(path)

"""Build and verify unpublished artifacts without choosing a CI or upload service."""

import argparse
from collections import Counter
from datetime import datetime, timezone
from email.parser import BytesParser
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from urllib.request import urlopen
import uuid
import venv
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BACKEND = "2.1.1"
BACKEND_FILE = "poetry_core-2.1.1-py3-none-any.whl"
BACKEND_URL = "https://files.pythonhosted.org/packages/19/ad/e3123a6351e8e23a36cc69c8d4e7891becb1932e4ab48ddbb7f709409c1c/" + BACKEND_FILE
BACKEND_SHA = "bc3b0382ab4d00d5d780277fd0aad1580eb4403613b37fc60fec407b5bee1fe6"
ROOT_FILES = ("pyproject.toml", "poetry.lock", "README.md", "LICENSE", "NOTICE.md", "CHANGELOG.md", "dbgpilot.example.toml")
SOURCE_TREES = ("src/dbgpilot", "docs", "examples", "scripts")
IGNORED = {"__pycache__", ".DS_Store", ".pytest_cache"}


class ValidationError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def export_source(root, target, epoch):
    paths = [root / name for name in ROOT_FILES]
    for tree in SOURCE_TREES:
        relative = Path(tree)
        require(not any((root / part).is_symlink() for part in (relative, *relative.parents)),
                f"Source export refuses symlink tree: {tree}")
        paths.extend(path for path in (root / tree).rglob("*") if path.is_file())
    manifest = {}
    for path in sorted(paths):
        relative = path.relative_to(root)
        if any(part in IGNORED for part in relative.parts) or path.suffix in {".pyc", ".pyo"}:
            continue
        require(not path.is_symlink(), f"Source export refuses symlink: {relative}")
        require(path.is_file(), f"Missing release input: {relative}")
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        destination.chmod(0o755 if path.suffix == ".sh" else 0o644)
        os.utime(destination, (epoch, epoch))
        manifest[relative.as_posix()] = digest(destination)
    return manifest


def safe_name(name):
    path = PurePosixPath(name)
    require(not path.is_absolute() and ".." not in path.parts and "\\" not in name,
            f"Unsafe archive member: {name}")


def metadata(raw, version, python):
    fields = BytesParser().parsebytes(raw)
    require(fields["Name"] == "dbgpilot" and fields["Version"] == version, "Distribution name/version mismatch")
    require(set(fields["Requires-Python"].replace(" ", "").split(",")) == set(python.replace(" ", "").split(",")),
            "Python support metadata mismatch")
    require((fields["License-Expression"] or fields["License"]) == "MIT", "Missing MIT license metadata")
    require(not fields.get_all("Requires-Dist"), "Core distribution acquired runtime dependencies")
    require(not fields.get_all("Provides-Extra"), "Validate newly declared extras before extending this checker")


def inspect_wheel(path, project, manifest, source):
    version = project["version"]
    prefix = f"dbgpilot-{version}.dist-info/"
    expected = {name.removeprefix("src/") for name in manifest if name.startswith("src/dbgpilot/")}
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), "Duplicate wheel members")
        for name in names:
            safe_name(name)
            require(name in expected or name.startswith(prefix), f"Unexpected wheel payload: {name}")
            require(not name.endswith((".php", ".pyc", ".so", ".pyd")), f"Forbidden wheel payload: {name}")
        require({name for name in names if name.startswith("dbgpilot/")} == expected, "Wheel package files differ from source")
        require("dbgpilot/py.typed" in names, "Typing marker missing")
        for name in expected:
            require(hashlib.sha256(archive.read(name)).hexdigest() == manifest["src/" + name], f"Wheel changed {name}")
        metadata(archive.read(prefix + "METADATA"), version, project["requires-python"])
        for name in ("LICENSE", "NOTICE.md"):
            require(archive.read(prefix + name) == (source / name).read_bytes(), f"Packaged {name} differs")
        require(b"dbgpilot=dbgpilot.cli:main" in archive.read(prefix + "entry_points.txt").replace(b" ", b""),
                "Console entry point missing")
    return names


def inspect_sdist(path, project, manifest):
    prefix = f"dbgpilot-{project['version']}/"
    with tarfile.open(path) as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        require(len(names) == len(set(names)), "Duplicate sdist members")
        files = {}
        for member in members:
            safe_name(member.name)
            require(member.isfile() or member.isdir(), f"Non-regular sdist member: {member.name}")
            require(member.name.startswith(prefix), "Unexpected sdist root")
            if member.isfile():
                files[member.name.removeprefix(prefix)] = archive.extractfile(member).read()
        require(set(files) == set(manifest) | {"PKG-INFO"}, "Sdist contains missing/unexpected files")
        for name, expected in manifest.items():
            require(hashlib.sha256(files[name]).hexdigest() == expected, f"Sdist changed {name}")
        metadata(files["PKG-INFO"], project["version"], project["requires-python"])
    return names


def backend_wheel(cache):
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / BACKEND_FILE
    if not target.exists():
        with urlopen(BACKEND_URL, timeout=30) as response:
            data = response.read(8 * 1024 * 1024 + 1)
        require(hashlib.sha256(data).hexdigest() == BACKEND_SHA, "Backend download checksum mismatch")
        temporary = cache / (BACKEND_FILE + "." + uuid.uuid4().hex)
        temporary.write_bytes(data)
        temporary.replace(target)
    require(digest(target) == BACKEND_SHA, "Cached backend checksum mismatch")
    return target


def python_in(environment):
    return environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def suite_evidence(path):
    root = ET.parse(path).getroot()
    for suite in root.iter("testsuite"):
        require(all(int(suite.get(key, "0")) == 0 for key in ("failures", "errors", "skipped")),
                "JUnit evidence reports failures/errors/skips")
    cases = list(root.iter("testcase"))
    require(cases, "JUnit evidence is empty")
    require(not any(case.find(tag) is not None for case in cases for tag in ("failure", "error", "skipped")),
            "JUnit evidence contains failures/errors/skips")
    modules = Counter(case.get("classname", "") for case in cases)
    required = {"tests.test_drupal": 4, "tests.test_compatibility": 6, "tests.test_browser": 1,
                "tests.test_integration": 1, "tests.test_proxy_integration": 1, "tests.test_stress": 1,
                "tests.test_setup_browser": 1, "tests.test_review_browser": 1, "tests.test_release": 1}
    require(all(modules[name] >= count for name, count in required.items()),
            "Full-suite evidence is missing required runtime/browser/Drupal/release cases")
    return {"tests": len(cases), "sha256": digest(path), "modules": dict(sorted(modules.items()))}


def validate(args):
    root = args.source.resolve()
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    version = project["version"]
    output = args.output.resolve() / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex[:8])
    output.mkdir(parents=True)
    logs = output / "logs"
    logs.mkdir()
    report = {"schema": 1, "version": version, "status": "running", "python": sys.version,
              "platform": platform.platform(), "source_date_epoch": args.source_date_epoch,
              "backend": {"name": "poetry-core", "version": BACKEND, "sha256": BACKEND_SHA},
              "publication": {"published": False, "destination": None, "authorized": False}, "checks": {}}
    env = {key: value for key, value in os.environ.items() if key not in {
        "PYTHONPATH", "PYTHONHOME", "DBGPILOT_TOKEN", "PYTEST_ADDOPTS", "PYTEST_PLUGINS",
    } and not key.startswith("PIP_")}
    env.update(PYTHONNOUSERSITE="1", PIP_CONFIG_FILE=os.devnull, PIP_NO_INDEX="1",
               PIP_DISABLE_PIP_VERSION_CHECK="1", SOURCE_DATE_EPOCH=str(args.source_date_epoch))

    def run(label, command, *, cwd, timeout=180):
        log = logs / (label + ".log")
        with log.open("w") as target:
            result = subprocess.run([str(item) for item in command], cwd=cwd, env=env,
                                    stdout=target, stderr=subprocess.STDOUT, timeout=timeout)
        require(result.returncode == 0, f"{label} failed; see {log}")
        return log

    try:
        require(sys.version_info[:2] in {(3, 12), (3, 13)}, "Use supported Python 3.12 or 3.13")
        require(args.source_date_epoch >= 0, "SOURCE_DATE_EPOCH must be nonnegative")
        run("poetry-check", ["poetry", "check", "--lock", "--strict"], cwd=root)
        require(f'__version__ = "{version}"' in (root / "src/dbgpilot/_version.py").read_text(), "Source version mismatch")
        require(f"## {version} — Unreleased" in (root / "CHANGELOG.md").read_text(), "Candidate changelog/version mismatch")
        with tempfile.TemporaryDirectory(prefix="dbgpilot-release-") as directory:
            work = Path(directory)
            source = work / "source-one"
            manifest = export_source(root, source, args.source_date_epoch)
            build_system = tomllib.loads((source / "pyproject.toml").read_text())["build-system"]
            require(build_system["requires"] == [f"poetry-core=={BACKEND}"], "Build backend must match the pinned validator")
            (output / "source-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
            report["source_manifest_sha256"] = digest(output / "source-manifest.json")
            wheelhouse = work / "wheelhouse"
            wheelhouse.mkdir()
            shutil.copyfile(backend_wheel(args.cache), wheelhouse / BACKEND_FILE)
            builder = work / "builder"
            venv.EnvBuilder(with_pip=True).create(builder)
            python = python_in(builder)
            run("backend-install", [python, "-m", "pip", "install", "--no-deps", "--no-cache-dir", wheelhouse / BACKEND_FILE], cwd=work)
            build = [python, "-c", "from poetry.core.masonry.api import build_sdist,build_wheel; build_sdist('dist'); build_wheel('dist')"]
            run("build-one", build, cwd=source)
            second = work / "source-two"
            require(export_source(root, second, args.source_date_epoch) == manifest, "Source changed during validation")
            run("build-two", build, cwd=second)
            wheel = source / "dist" / f"dbgpilot-{version}-py3-none-any.whl"
            sdist = source / "dist" / f"dbgpilot-{version}.tar.gz"
            for artifact in (wheel, sdist):
                require(digest(artifact) == digest(second / "dist" / artifact.name), f"Build is not byte reproducible: {artifact.name}")
            members = {wheel.name: inspect_wheel(wheel, project, manifest, source),
                       sdist.name: inspect_sdist(sdist, project, manifest)}
            (output / "contents.json").write_text(json.dumps(members, indent=2) + "\n")
            report["checks"].update(metadata_and_lock=True, archive_contents=True, byte_reproducible=True)
            probes = work / "probes"
            probes.mkdir()
            shutil.copyfile(source / "scripts/probe_install.py", probes / "probe_install.py")
            shutil.copyfile(source / "examples/first_breakpoint.py", probes / "first_breakpoint.py")
            for kind, artifact in (("wheel", wheel), ("sdist", sdist)):
                install = work / ("installed-" + kind)
                venv.EnvBuilder(with_pip=True).create(install)
                installed_python = python_in(install)
                run(kind + "-install", [installed_python, "-m", "pip", "install", "--no-deps", "--no-cache-dir",
                                      "--find-links", wheelhouse, artifact], cwd=probes)
                run(kind + "-probe", [installed_python, probes / "probe_install.py"], cwd=probes, timeout=40)
                report["checks"][kind + "_fresh_install_and_roundtrip"] = True
                if args.live_php:
                    run(kind + "-first-breakpoint", [installed_python, probes / "first_breakpoint.py", "--launch", "--php", args.php],
                        cwd=probes, timeout=40)
                    report["checks"][kind + "_live_php_onboarding"] = True
            if args.live_browser:
                report["optional_validation_dependencies"] = {
                    name: importlib.metadata.version(name) for name in ("playwright", "pytest", "pytest-asyncio")
                }
                run("installed-browser-examples", [sys.executable, root / "scripts/check_setup_examples.py", "--wheel", wheel, "--live"],
                    cwd=root, timeout=120)
                report["checks"]["installed_browser_examples"] = True
            if args.suite_junit:
                report["full_suite"] = suite_evidence(args.suite_junit)
                evidence = output / "evidence"
                evidence.mkdir()
                shutil.copyfile(args.suite_junit, evidence / "junit.xml")
                for name in ("compatibility.json", "drupal11.json", "review-junit.xml", "fast-py312.xml", "fast-py313.xml"):
                    path = root / "test-results" / name
                    if path.is_file():
                        shutil.copyfile(path, evidence / name)
            report["artifacts"] = {}
            for artifact in (wheel, sdist):
                shutil.copyfile(artifact, output / artifact.name)
                report["artifacts"][artifact.name] = {"sha256": digest(artifact), "bytes": artifact.stat().st_size}
            (output / "SHA256SUMS").write_text("".join(f"{info['sha256']}  {name}\n" for name, info in sorted(report["artifacts"].items())))
        report["status"] = "validated-unpublished-candidate"
        checklist = ["# Release candidate checklist", "", f"Version: {version}. Status: unpublished.", "",
                     "Full-suite tests and CI are optional for a manual artifact handoff.",
                     "Consumer quickstart: docs/consumer-quickstart.md in the source archive.", "",
                     "- [x] Metadata, public imports, versions, license and typing marker checked.",
                     "- [x] Two isolated builds produced identical wheel and source artifacts.",
                     "- [x] Wheel and source installed in separate bare environments; HTTP/TCP reconnect probes passed.",
                     f"- [{'x' if args.live_php else ' '}] Optional: real PHP first-breakpoint onboarding passed for both installs.",
                     f"- [{'x' if args.live_browser else ' '}] Optional: installed standalone and pytest Chromium examples passed.",
                     f"- [{'x' if args.suite_junit else ' '}] Optional: passing full-suite evidence supplied and copied.",
                     "- [ ] Optional: choose and configure CI runners/triggers/required checks.",
                     "- [ ] Establish publication destination and source/documentation URLs.",
                     "- [ ] Release operator supplies credentials and explicit publication authorization.",
                     "- [ ] Publish these exact verified artifact hashes and record the result."]
        (output / "CHECKLIST.md").write_text("\n".join(checklist) + "\n")
        print(json.dumps({"status": report["status"], "version": version, "output": str(output), "checks": report["checks"]}))
        return output
    except Exception as error:
        report.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        (output / "validation.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/release-candidate")
    parser.add_argument("--cache", type=Path, default=Path(tempfile.gettempdir()) / "dbgpilot-release-tools")
    parser.add_argument("--source-date-epoch", type=int, default=int(os.environ.get("SOURCE_DATE_EPOCH", "315532800")))
    parser.add_argument("--live-php", action="store_true")
    parser.add_argument("--php", default="php")
    parser.add_argument("--live-browser", action="store_true")
    parser.add_argument("--suite-junit", type=Path)
    args = parser.parse_args()
    try:
        validate(args)
    except (ValidationError, OSError, subprocess.TimeoutExpired) as error:
        parser.exit(1, f"Distribution validation failed: {error}\n")


if __name__ == "__main__":
    main()

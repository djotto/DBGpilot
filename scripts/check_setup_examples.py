"""Validate the setup examples against a wheel, optionally with real PHP/Chromium.

Run using the development environment. Optional test dependencies are shared
from that environment AFTER verifying the installed stdlib-only core. Neither
the source tree nor its editable-install .pth files are added to the new env.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sysconfig
import tempfile
import tomllib
import venv


def main():
    root = Path(__file__).resolve().parents[1]
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, default=root / f"dist/dbgpilot-{version}-py3-none-any.whl")
    parser.add_argument("--live", action="store_true", help="Run examples against the prepared DDEV checkout site")
    args = parser.parse_args()
    wheel = args.wheel.resolve(strict=True)
    env = {key: value for key, value in os.environ.items() if key not in {
        "PYTHONPATH", "PYTHONHOME", "DBGPILOT_TOKEN", "DBGPILOT_EXAMPLE_CONFIG",
        "DBGPILOT_EXAMPLE_PAGE_URL", "DBGPILOT_EXAMPLE_LINE", "PYTEST_ADDOPTS", "PYTEST_PLUGINS",
    }}
    with tempfile.TemporaryDirectory(prefix="dbgpilot-examples-") as directory:
        work = Path(directory)
        install = work / "installed"
        venv.EnvBuilder(with_pip=True).create(install)
        python = install / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

        def run(*command, **kwargs):
            return subprocess.run([str(item) for item in command], cwd=work, env=env, check=True, **kwargs)

        run(python, "-m", "pip", "install", "--no-deps", "--no-index", "--no-cache-dir", wheel)
        run(python, "-c", """import importlib.util, sys, dbgpilot
assert dbgpilot.__file__.startswith(sys.prefix)
assert importlib.util.find_spec('pytest') is None
assert importlib.util.find_spec('playwright') is None
from dbgpilot import DebuggerSetup, SetupConfig, SetupError
assert DebuggerSetup().config.launch is False
""")
        purelib = Path(json.loads(run(python, "-c", "import json, sysconfig; print(json.dumps(sysconfig.get_path('purelib'))) ",
                                      capture_output=True, text=True).stdout))
        # Append the dependency directory without executing its editable .pth.
        (purelib / "optional-test-dependencies.pth").write_text(sysconfig.get_path("purelib") + "\n")
        run(python, "-c", "import sys, dbgpilot, pytest, pytest_asyncio, playwright; assert dbgpilot.__file__.startswith(sys.prefix)")
        shutil.copytree(root / "examples", work / "examples")
        run(python, work / "examples/checkout_debug.py", "--help")
        run(python, "-m", "pytest", "--collect-only", "-q", work / "examples/pytest",
            "-o", "asyncio_default_fixture_loop_scope=function")
        if args.live:
            source = root / "src/checkout.php"
            line = next(index for index, text in enumerate(source.read_text().splitlines(), 1)
                        if "// BREAKPOINT:" in text)
            run(python, work / "examples/checkout_debug.py", "--launch", "--port", "0",
                "--source", source, "--line", line)
            env.update(DBGPILOT_EXAMPLE_LAUNCH="1", DBGPILOT_EXAMPLE_SOURCE=str(source),
                       DBGPILOT_EXAMPLE_LINE=str(line))
            run(python, "-m", "pytest", "-q", work / "examples/pytest",
                "-o", "asyncio_default_fixture_loop_scope=function", "-W", "error")
        print("Installed wheel, stdlib-only core, standalone help and pytest collection passed.")
        print("Live PHP/browser examples passed." if args.live else "Live PHP/browser examples were not requested.")


if __name__ == "__main__":
    main()

"""Build pinned historical Xdebug modules in DDEV's development cache.

Run with ddev poetry run python scripts/prepare_test_runtimes.py. This does not
replace the Xdebug extension used by the application or its PHP-FPM service.
"""

import hashlib
import json
import os
import platform
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
CACHE = Path("/mnt/ddev-global-cache/dbgpilot/runtimes")
SOURCES = (
    ("8.2", "3.3.2", "15545b8311bedb5e7df08fd90d6653d9bf33629791e8119e70350475df932c55"),
    ("8.3", "3.4.7", "7592923501e3fdb9741ad35b90e08fc6b3c5dd31eadc4c83b7b3c9dda0627b24"),
)
PROXIES = {
    "x86_64": ("https://xdebug.org/files/binaries/dbgpProxy", "223f130579395dd5b14af7ae9b1034adde8eb7a9508af2116356b557513121eb"),
    "aarch64": ("https://xdebug.org/files/binaries/dbgpProxy-arm64", "c23f811f58cc04affefafbffe0f436674deec4c5ddd4205439da285b1cd25233"),
}


def run(*args, **kwargs):
    subprocess.run(args, check=True, **kwargs)


def main():
    if not os.environ.get("DDEV_SITENAME"):
        raise SystemExit("Run this inside DDEV")
    CACHE.mkdir(parents=True, exist_ok=True)
    architecture = platform.machine()
    if architecture not in PROXIES:
        raise SystemExit(f"No pinned proxy test binary for {architecture}")
    proxy_url, proxy_digest = PROXIES[architecture]
    proxy = CACHE / f"dbgpProxy-0.6.2-{architecture}"
    if not proxy.exists():
        with urlopen(proxy_url, timeout=60) as response:
            payload = response.read()
        if hashlib.sha256(payload).hexdigest() != proxy_digest:
            raise RuntimeError(f"Checksum mismatch: {proxy_url}")
        proxy.write_bytes(payload)
        proxy.chmod(0o755)
    if hashlib.sha256(proxy.read_bytes()).hexdigest() != proxy_digest:
        raise RuntimeError(f"Cached proxy checksum mismatch: {proxy}")
    version = subprocess.check_output([str(proxy), "-v"], text=True)
    if "Xdebug DBGp proxy (0.6.2)" not in version:
        raise RuntimeError("Unexpected proxy test version")
    needed = any(not (CACHE / f"php{php}-xdebug{version}.so").exists() for php, version, _ in SOURCES)
    if needed:
        run("sudo", "env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "update", "-qq")
        run("sudo", "env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install", "-y", "--no-install-recommends",
            "build-essential", "autoconf", "pkg-config", "php8.2-dev", "php8.3-dev")
    results = []
    for php, version, digest in SOURCES:
        module = CACHE / f"php{php}-xdebug{version}.so"
        if not module.exists():
            url = f"https://xdebug.org/files/xdebug-{version}.tgz"
            with urlopen(url, timeout=60) as response:
                payload = response.read()
            if hashlib.sha256(payload).hexdigest() != digest:
                raise RuntimeError(f"Checksum mismatch: {url}")
            with tempfile.TemporaryDirectory(prefix="dbgpilot-build-") as temporary:
                directory = Path(temporary)
                archive = directory / "source.tgz"
                archive.write_bytes(payload)
                with tarfile.open(archive) as source:
                    source.extractall(directory, filter="data")
                source_dir = directory / f"xdebug-{version}"
                log = CACHE / f"php{php}-xdebug{version}.build.log"
                with log.open("w") as output:
                    options = {"cwd": source_dir, "stdout": output, "stderr": subprocess.STDOUT}
                    run(f"phpize{php}", **options)
                    run("./configure", f"--with-php-config=/usr/bin/php-config{php}", "--enable-xdebug", **options)
                    run("make", "-j2", **options)
                shutil.copy2(source_dir / "modules/xdebug.so", module)
        args = [f"/usr/bin/php{php}", "-n", "-d", f"zend_extension={module}"]
        info = json.loads(subprocess.check_output(args + ["-r", "echo json_encode([PHP_VERSION, phpversion('xdebug')]);"]))
        if info[1] != version:
            raise RuntimeError(f"Unexpected Xdebug version: {info}")
        results.append({"php": info[0], "xdebug": info[1], "args": args})
    (CACHE / "manifest.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps({"event": "runtimes_ready", "runtimes": results, "proxy": str(proxy)}), flush=True)


if __name__ == "__main__":
    main()

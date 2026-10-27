# Rehearse and hand off a release

This process prepares **unpublished DBGpilot 0.1.0 candidate artifacts**. It does
not choose CI hosting, schedule jobs, upload packages, create tags or obtain
credentials. Publication is a separate operator-authorized step.

## Local entry points

Use a development checkout, Python 3.12 or 3.13, and Poetry 2.1.1. The backend
already used by the project is pinned to `poetry-core==2.1.1`; it is a build
dependency only. Development tools come from `poetry.lock`.

```sh
poetry install
# No PHP/browser/Docker; needs permission to bind loopback TCP:
./scripts/check_fast.sh test-results/fast-junit.xml
# Packaging and bare installed HTTP/TCP probes, without PHP/browser/Docker:
poetry run python scripts/check_distribution.py
```

Run fast checks under each supported interpreter rather than assuming one run
covers both. In this workspace, the host environment uses Python 3.12 and the
parent DDEV environment uses Python 3.13. A Linux/macOS shell is required by the
shell entry points; the package validator itself is stdlib Python. Fast checks
need the development tests; the source archive instead carries everything needed
for distribution validation and the standalone first-breakpoint example.

The complete local acceptance command is:

```sh
./scripts/check.sh
```

It prepares/requires Drupal, installs existing development/browser/runtime
tooling, runs all tests without permitting a missing required Drupal fixture,
then performs isolated distribution validation with real PHP onboarding and
installed Chromium/pytest examples. It uses the existing DDEV/Docker harness;
it does not install Docker or select a future hosted runner.

The equivalent distribution-only invocation after full-suite evidence exists:

```sh
ddev poetry run python scripts/check_distribution.py --live-php --live-browser \
  --suite-junit test-results/junit.xml
```

`--live-php` runs the generated local PHP example from both fresh installs.
`--live-browser` additionally runs the existing standalone and pytest examples
against the installed wheel and prepared checkout PHP site. Optional browser
validation deliberately exposes the development environment's Playwright/pytest
dependencies only after bare-core isolation has passed. There are no declared
package extras. The report records the optional tool versions; the core probe
requires pytest and Playwright to be absent.

## What the validator does

1. Checks Poetry metadata/lock consistency, Python support and version alignment.
2. Copies an explicit source allowlist into two temporary clean exports. It
   refuses source symlinks and excludes caches, generated/vendor fixtures,
   private handoffs and local outputs. No `.git` directory is required or
   invented; an export is not claimed to be a clean VCS checkout.
3. Downloads/caches the pinned backend wheel from its fixed upstream URL,
   verifies its SHA-256, and installs it in a fresh build environment. The
   checked checksum and backend version are included in the report.
4. Normalizes file modes/times and sets `SOURCE_DATE_EPOCH` (default 315532800,
   the ZIP-compatible epoch, not a release/publication date). Builds both
   formats twice and requires byte-for-byte equality within that environment.
5. Inspects exact archive contents and hashes against the exported source.
   Checks metadata, zero runtime dependencies, typing marker, MIT license,
   provenance notice and CLI entry point. PHP/Drupal fixtures, downloaded
   reference projects and binaries cannot enter the package payload.
6. Installs wheel and source into separate fresh environments with no source
   path injection, pytest or Playwright. The source install uses pip's isolated
   build with the local verified backend wheel; no runtime index access is
   needed. Checks all public exports, versions, console/module CLI, and real
   HTTP/TCP snapshot/reconnect behavior with an explicitly scripted peer.
7. Runs requested real PHP/browser checks. Supplied full-suite JUnit must have
   no failures/errors/skips and include the required Drupal/runtime/browser,
   proxy, stress and release cases; a fast-only report is rejected. Copies it
   and available runtime/fast-check evidence.
8. Copies the verified artifacts into a new candidate directory, creates hashes,
   logs, source/contents manifests, a validation report and release checklist.

Source is checked again before the second export, so editing inputs while
validation runs fails rather than silently mixing versions. JUnit evidence is
copied as supplied: run the full command in the same checkout. It is not a
cryptographic attestation binding arbitrary old tests to new source. Repeated
build equality is measured under the recorded interpreter/backend/environment;
it is not an untested promise of identical compression across every platform.

The backend cache defaults to the system temporary directory. Use `--cache`
for a persistent cache, `--source-date-epoch` to set a deliberate reproducibility
timestamp, and `--output` to select the candidate parent directory. Every run
creates its own subdirectory; existing candidates are never overwritten.
Failures retain a failed report and logs, and do not copy artifacts into the
candidate's root as though validation passed.

## Review the candidate

Under `dist/release-candidate/<run>/`, review:

- `validation.json`: checks, interpreter/platform, backend, source manifest hash,
  artifact hashes and explicit `published: false`/unset destination.
- `source-manifest.json` and `contents.json`: source hashes and archive contents.
- `SHA256SUMS`, the wheel and source archive: the exact files to hand off.
- `logs/`: build, install, bare-core, roundtrip and requested live examples.
- `evidence/`: supplied full JUnit and available runtime/Drupal/review reports.
- `CHECKLIST.md`: completed checks and deliberately pending operator decisions.

Follow [installation](installation.md) using those files. The first-breakpoint
walkthrough is verified from installed artifacts, with no development source
imports. Do not substitute an older wheel from the top-level `dist/` directory.

## Operator decisions and publication

The remaining checklist is intentionally open:

- Select CI provider, runner images/architecture, triggers, caches, artifact
  retention and required checks. These local entry points make no such choices.
- Select a distribution destination and establish source/documentation URLs;
  check package-name availability and its account/ownership requirements.
- Have the release operator supply destination-specific credentials securely
  and explicitly authorize the upload of the reviewed artifact hashes.
- Recheck changelog/version, support evidence and hashes immediately before
  upload. Use the chosen destination's supported upload mechanism against these
  exact files, rather than rebuilding after approval.
- Record destination, published version, artifact hashes, time and authorization
  after upload. Retain the candidate evidence; a local rehearsal is not a
  publication record.

For a future PyPI-compatible destination, tools such as Twine can inspect/upload
these standard artifacts, but no default live registry or credential is wired
into this process. No upload command is executed by any validation entry point.

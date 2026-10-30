# Rehearse and hand off a release

This process prepares **unpublished DBGpilot 0.1.1 candidate artifacts**. It does
not choose CI hosting, schedule jobs, upload packages, create tags or obtain
credentials. Publication is a separate operator-authorized step. While testing,
build and share candidates manually; a passing full suite and hosted CI are not
required for an artifact handoff.

## Local entry points

Use a development checkout, Python 3.12 or 3.13, and Poetry 2.1.1. The backend
already used by the project is pinned to `poetry-core==2.1.1`; it is a build
dependency only. Development tools come from `poetry.lock`.

```sh
poetry install
./scripts/release.sh
# Use the output directory printed in the final JSON: dist/release-candidate/<run>/.
# Full tests are separate, optional manual checks:
# No PHP/browser/Docker; needs permission to bind loopback TCP:
./scripts/check_fast.sh test-results/fast-junit.xml
# Packaging and bare installed HTTP/TCP probes, without PHP/browser/Docker:
poetry run python scripts/check_distribution.py
```

`./scripts/release.sh` wraps that same validator. It builds wheel/source twice,
checks their contents, installs both in fresh environments and exercises the
small installed HTTP/TCP probes. It does not run pytest, prepare PHP/Drupal,
launch a browser, require full-suite results, create tags or upload files.
The first build needs network access to fetch the checksum-pinned backend if
it is not cached. Poetry and Python 3.12/3.13 must be installed.

All validator options pass through, for example
`./scripts/release.sh --output dist/testing` or `./scripts/release.sh --help`.
Paths supplied to the shell wrapper are resolved from this repository's root.
Inside the prepared DDEV environment, use
`ddev poetry run bash scripts/release.sh` to select its container environment.
Use the [consumer quickstart](consumer-quickstart.md) to try the resulting wheel
in another project's pytest / async Playwright environment. The source archive
includes that guide and `examples/consumer/`.

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

## Manual upload

For local testing, install the wheel straight from the candidate directory. To
share it, upload these three files from **one successful run** to your chosen
download host, release attachment area or shared folder:

- `dbgpilot-0.1.1-py3-none-any.whl`
- `dbgpilot-0.1.1.tar.gz` (includes the quickstart and copyable pytest example)
- `SHA256SUMS`

Keep `validation.json`, inventories and logs locally. Review its `checks` to see
which optional tests were actually requested. An omitted full-suite report is
allowed; do not describe it as a passing full suite. CI can be added separately.

Set the path to the successful run printed by the command, then verify hashes:

```sh
candidate=/absolute/path/to/dist/release-candidate/REPLACE_WITH_RUN
(cd "$candidate" && shasum -a 256 -c SHA256SUMS)
```

Upload those existing files through your host's normal UI. Use a distinct
download location for each testing candidate and retain its checksum file.
Consumers can download/install the wheel from that location using
[`pip install /path/to/file.whl`](https://pip.pypa.io/en/stable/cli/pip_install/).
No PyPI account is needed.

### GitHub release command

This checkout's GitHub origin is `djotto/DBGpilot`. Once shared, consumers can
find artifacts on [its Releases page](https://github.com/djotto/DBGpilot/releases).
The repository is public; a published release's wheel can be installed directly
from its download URL. A draft is visible only to repository collaborators.

Install the [GitHub CLI](https://cli.github.com/) and authenticate using
`gh auth login` if needed. Commit and push the source changes you want to share,
then build with `./scripts/release.sh`. Use the successful run's candidate path.
Create and push a unique testing tag for that same commit:

```sh
git tag v0.1.1-testing.1
git push origin v0.1.1-testing.1
```

Preview the upload locally:

```sh
poetry run python scripts/github_release.py "$candidate" \
  --tag v0.1.1-testing.1 --dry-run
```

The command verifies the successful packaging/install report, source manifest
checksum and exact wheel/source/checksum files. It generates release notes with
the install command, a pinned consumer-quickstart link, and the validation scope.
The default repository comes from GitHub `origin`; override it with
`--repo OWNER/REPOSITORY` if needed. A dry run contacts no GitHub service and
writes no files. Ensure the chosen tag's source matches the candidate; the
uploader checks artifact integrity and remote tag existence, not source/tag
equivalence.

Upload those files to a **draft prerelease** for review:

```sh
poetry run python scripts/github_release.py "$candidate" --tag v0.1.1-testing.1
```

This writes `GITHUB_RELEASE_NOTES.md` alongside the candidate and invokes
`gh release create`. It requires an existing pushed tag, uploads only the three
validated files, and does not mark the prerelease as Latest. It runs no tests
and does not create/push commits or tags. Full-suite results are optional.

Publish that draft from the GitHub UI, or run:

```sh
gh release edit v0.1.1-testing.1 --repo djotto/DBGpilot --draft=false
```

To create a published prerelease immediately instead of a draft, use
`--publish` on the initial upload command. Use a new testing tag for each new
candidate. Existing releases/assets are not overwritten. After a partially
failed upload, inspect the draft and use
[`gh release upload`](https://cli.github.com/manual/gh_release_upload) to add
missing verified assets, or delete that draft before retrying.

The generated release notes give consumers a command like:

```sh
python -m pip install 'https://github.com/djotto/DBGpilot/releases/download/v0.1.1-testing.1/dbgpilot-0.1.1-py3-none-any.whl'
```

That URL starts working after publication. The notes include its wheel hash as
a `#sha256=...` fragment. For a private fork, consumers instead download the
asset while authenticated and install the local file. See
[`gh release create`](https://cli.github.com/manual/gh_release_create) and
[`gh release edit`](https://cli.github.com/manual/gh_release_edit) for the
underlying commands. Upload happens only when you run the uploader without
`--dry-run`; the local `release.sh` build command still uploads nothing.

After sharing, record the download/release URL, candidate run, version, hashes,
date and manual checks in your release notes. The validator's `publication`
fields describe its local build time; it does not track subsequent manual
uploads. Keep a separate sharing record instead of treating them as live status.

Published patch updates receive a new package version, currently `0.1.1`.
When retrying a testing build with the same version, explicitly install the new file:

```sh
python -m pip install --force-reinstall --no-deps /path/to/new/dbgpilot-0.1.1-py3-none-any.whl
```

Restart any daemon you intend to upgrade; installing a wheel does not replace a
running process, and restart loses live session IDs. For published versioned
releases, bump the package version rather than replacing an old version's files.
PyPI publishing is deferred; no package-registry credentials or upload automation
are configured by this workflow.

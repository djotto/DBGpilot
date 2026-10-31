# Distribution and releases

[Documentation index](../README.md#documentation) · [Development](development.md)

## Current distribution

The repository root is the `dbgpilot` package. It has CommonJS/ESM entry points,
TypeScript declarations, a standalone example and bundled Markdown documentation.
The main entry point provides the Playwright Test fixture; `dbgpilot/core` provides
the independent debugger. No compile step or Python runtime is required.

No JavaScript GitHub release or registry package is published yet. `private: true`
prevents accidental npm registry publication. Git, local source and tarball installs
still work. Packaging never uploads an artifact or changes GitHub releases.

## Local candidate

From the checkout:

```sh
npm ci
npm run check:package
```

Or use `./scripts/release.sh`, which runs that same local package validation.
Review `test-results/js-package-validation.json` for the actual file list,
SHA-256, version and clean-install evidence. The tarball is
`dist/js-candidate/dbgpilot-<version>.tgz`.

Install it in another project:

```sh
npm install --save-dev /absolute/path/dbgpilot-0.1.0.tgz @playwright/test
```

Use the actual generated version filename. A tarball tests the shipped payload;
a local source dependency may instead link to your working checkout. Run a real
website test in the target environment after installing: package validation
cannot prove that environment's PHP networking, paths and Xdebug settings.

## GitHub installation

After the desired source commit is available on GitHub:

```sh
npm install --save-dev dbgpilot@github:djotto/DBGpilot#main @playwright/test
```

Use a reviewed commit SHA in place of `main` for a specific pin, and commit the
consumer's lockfile. Local-only changes require a local install or candidate
until they are pushed. The package rename uses `dbgpilot` / `dbgpilot/core`
imports; choose a source revision containing that package name.

## Preparing a published release

1. Update package version, lockfile and changelog together. Choose a distinct JS
   tag, such as `js-v0.1.0-testing.1`, so historical Python tags stay identifiable.
2. Run the [full checks](development.md#full-environment), then review the clean
   package report and candidate artifact for that exact source tree.
3. Commit the reviewed source locally. Push, create a tag, or create a GitHub
   draft only when publication work is explicitly requested.
4. If using GitHub releases, attach the validated npm tarball to the draft.
   Review the notes and publish the draft as a separate explicit action.

GitHub's automatic source archive includes the development tree; it is not the
validated npm tarball. Consumers can install the release asset URL or a source
tag according to their needs. Do not add automatic uploads to setup or tests.

An npm registry release would additionally require deliberately changing
`private`, selecting an available package/account namespace, and configuring npm
publishing credentials/access. That is separate from the current source/tarball
workflow; no registry publication is performed by this project today.

## Python archive

`archive/python` preserves commit `f3ce1ecb654137cc356b3a49f3f966d67db6ed8e`, the
final Python main branch (0.1.1). Historical tags `v0.1.0-testing.1` and
`v0.1.1-testing.1` still identify their original source. Their GitHub testing
releases were converted to unpublished drafts on 2026-10-30; the original assets
are retained with those drafts. Local backups and hashes are under ignored
`dist/python-release-backup/`. Already-downloaded copies are outside this
repository's control. The active JS package does not depend on the archive.

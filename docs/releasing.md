# GitHub distribution

The repository root is the `dbgpilot` package. It can be installed
directly from GitHub without a build step, Python, a registry or a release asset:

```sh
npm install --save-dev dbgpilot@github:djotto/DBGpilot#main @playwright/test
```

Use a reviewed commit SHA in place of `main` for an explicit pin. Commit the
consumer's npm lockfile. The package exports both CommonJS and ESM, with public
TypeScript declarations and a separate `dbgpilot/core` entry point.

No JavaScript GitHub release or registry package is published yet. `private: true`
prevents accidental npm registry publication; Git and tarball installs still work.

To prepare a release candidate:

1. Update the package version, lockfile and changelog together. Choose a distinct
   JS tag (for example `js-v0.1.0-testing.1`) so historical Python tags stay clear.
2. Run the full checks described in [development](development.md).
3. Run `npm run check:package` or `./scripts/release.sh`. Review the artifact,
   SHA-256 and clean-install evidence in `test-results/js-package-validation.json`.
4. Commit the reviewed source. Create a tag at that commit and a draft GitHub
   prerelease with `dist/js-candidate/dbgpilot-<version>.tgz` attached.
   Review its notes and publish the draft as a separate explicit action.

Consumers can install the attached tarball URL or the JS tag. Do not treat
GitHub's automatic source archive as the validated npm tarball: it includes the
development tree, whereas the npm artifact has an explicit runtime allowlist.
No automatic upload or registry publication runs during setup, tests or packing.

## Python archive

`archive/python` preserves commit `f3ce1ecb654137cc356b3a49f3f966d67db6ed8e`,
the final Python main branch (version 0.1.1). Historical tags
`v0.1.0-testing.1` and `v0.1.1-testing.1` still identify their original source.
Both GitHub testing releases were converted to unpublished drafts on 2026-10-30.
Their wheel, source archive and manifest assets are retained with those drafts.
Local backups and SHA-256 records are under ignored `dist/python-release-backup/`.
Published copies already downloaded elsewhere are outside this repository's control.

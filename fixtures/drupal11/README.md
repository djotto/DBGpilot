# DBGpilot Drupal 11 fixture

From the parent DBGpilot project root:

```sh
ddev drupal-setup
ddev test-setup
ddev drupal-test
```

Open https://dbgpilot-drupal11.ddev.site and log in with
`admin` / `dbgpilot-admin`.

Drupal 11.4.11 and Drush 13.8.0 are locked by Composer. The site has its own
MariaDB database and sends Xdebug connections to the parent project's Node/Playwright
container. Core and vendor code remain unmodified. Setup seeds its own admin
account and page; tests create and delete their own additional content.

See [development](../../docs/development.md) and the root README for network
routing, path mappings, fixture startup and test coverage.

This fixture uses Drupal's GPL-2.0-or-later project template/dependencies.
Those development applications are separate from DBGpilot's MIT JavaScript package
and are not included in its npm tarball.

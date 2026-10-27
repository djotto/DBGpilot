# Drupal 11 acceptance fixture

The project includes a separate DDEV site at
[https://dbgpilot-drupal11.ddev.site](https://dbgpilot-drupal11.ddev.site).
It runs Drupal **11.4.11**, PHP 8.4, Xdebug, and MariaDB 11.8. Its own database
is independent of the small checkout harness. Drupal and its dependencies are
pinned in `fixtures/drupal11/composer.lock`; `composer install` restores them.
Drush 13.8.0 is a fixture development dependency. Python runtime dependencies
remain empty, and Drupal's downloaded code is excluded from DBGpilot packages.

## Set up and run

From the DBGpilot project root on the host:

```sh
ddev drupal-setup
ddev test-setup
ddev drupal-test
```

The first command invokes `scripts/setup_drupal.sh`, starts both DDEV projects,
installs the locked Composer dependencies, and installs/seeds the Drupal site.
The browser setup follows project startup because recreated containers need
their Playwright system libraries restored. `./scripts/check.sh` performs the
full setup and runs all tests, requiring the Drupal fixture to be available.

Fixture login: **admin / dbgpilot-admin** at `/user/login`. These are development
fixture credentials. The front page is the seeded basic page, initially node 1.
Setup explicitly creates its content type, body storage/field/display, and one
page with a fixed UUID. The Standard profile supplies the ordinary Drupal
modules, Olivero front-end theme, Claro admin theme, and user roles.

Repeated setup resets the fixture-owned admin account and seeded page, retaining
the page ID and other content. It does not reinstall an already bootstrapped
site. An unbootstrappable site with a populated database fails rather than being
silently reinstalled. Successful setup writes `fixture-state.json` with versions,
database version, and seeded page details; this generated file is ignored.

The fixture's development settings disable page/render/dynamic-page caches and
asset aggregation so core breakpoints remain reachable on repeated requests.
Drupal core and vendor files are unmodified. Generated code, site files, and
database credentials/settings created by DDEV are not Python dependencies.

## Debugging Drupal manually

Run the persistent server in the parent DBGpilot container:

```sh
ddev poetry run dbgpilot serve --xdebug-host 0.0.0.0 \
  --config fixtures/drupal11/dbgpilot.toml
```

The API remains on loopback `127.0.0.1:9004`. The debugger listener accepts port
9003 from the Drupal container. Its Xdebug configuration points at
`ddev-xdebug-web`, the parent container's Docker DNS name, using DDEV's shared
network. The existing checkout harness can still connect to the same listener.
Do not run this standalone server while acceptance tests own port 9003.

The fixture mapping translates the parent container's local source paths:

```text
/var/www/html/fixtures/drupal11/ → file:///var/www/html/
```

The [Python setup guide](python-setup.md#ddev-and-drupal) also shows explicitly
owned startup through `DebuggerSetup`, with the same fixture configuration,
reconnection, and deliberate shutdown. The Drupal tests include that entry point.

This includes Drupal's `web/core` and Composer `vendor` directories. Set
breakpoints using the local source files while inspecting the separate Drupal
process. For clients sending host paths, override the local root with the
absolute host fixture directory; see [path mapping](path-mapping.md).

Browser scripts inside the parent container use
`http://ddev-dbgpilot-drupal11-web`, which is included in Drupal's trusted hosts.
The public DDEV URL is for the host browser. The test setup does not publish the
debugger/API ports to the host or change Xdebug's network configuration elsewhere.

## What the acceptance tests prove

`tests/test_drupal.py` runs actual Chromium against Drupal PHP-FPM/Xdebug:

1. **Core node rendering:** break inside
   `Drupal\Core\Entity\Controller\EntityViewController::view`, inspect the node
   and its label, return a snapshot while navigation waits, close the first
   client, reconnect, mutate the label, step, and complete the response. A fresh
   request verifies the database title remained unchanged.
2. **Content save through Form API:** log in, fill the normal node-creation form,
   break immediately before `NodeForm::save` saves the entity, reconnect, change
   the title, step through the save, and finish the redirect. A fresh page load
   verifies the changed title persisted. The test deletes its own created node.
3. **Actual author-autocomplete AJAX:** type into Drupal's normal author widget,
   pause in `EntityAutocompleteController` before matching users, inspect and
   change the query, step through the database-backed matcher, and resume. The
   admin suggestion appears in Drupal's autocomplete menu. The typing action
   completes while the AJAX request remains paused.

Breakpoints are located by unique statements in the pinned source, with no
test instrumentation added to Drupal core. Snapshots assert local/engine paths,
real variables, and framework frames. `test-results/drupal11.json` records exact
runtime versions, observed frames, source locations, and successful scenarios.
`test-results/drupal11.png` captures the seeded front page; JUnit is written by
the full check command.

A useful observed detail: Drupal renders these controllers within PHP Fibers.
At these stops Xdebug reports the active render-Fiber stack, ending at its Fiber
entry; the parent Symfony HttpKernel stack is not included. DBGpilot preserves
the engine's stack rather than inventing parent frames. These tests verify
debugging within that actual execution context.

Bare pytest runs skip the optional Drupal tests if their fixture state is absent.
`ddev drupal-test` requires setup and fails if it is missing; a previously prepared
but stopped/unreachable site also fails. Tests are sequential because they share
the fixed PHP debugger port. They establish these workflows for this pinned
Drupal site, not general coverage of all Drupal modules, recipes, or deployments.

## Stopping the fixture

```sh
cd fixtures/drupal11
ddev stop
```

This keeps its database. Run setup again from the project root to restart/reseed.
The parent project's existing checkout site remains a separate DDEV project.

Installation references: [Drupal's release](https://www.drupal.org/project/drupal/releases/11.4.11),
[DDEV Drupal quickstart](https://docs.ddev.com/en/stable/users/quickstart/#drupal),
and [DDEV architecture/networking](https://docs.ddev.com/en/stable/users/usage/architecture/).

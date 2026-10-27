"""Actual Drupal core, Form API, database, Chromium, and cross-container Xdebug."""

import json
import os
from pathlib import Path
import uuid

import pytest

from dbgpilot import BreakpointSpec, Client, DebuggerSetup, PathMapping, PlaywrightDebugger, Server

pytestmark = [pytest.mark.integration, pytest.mark.browser, pytest.mark.drupal]
ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures/drupal11"
REPORT = ROOT / "test-results/drupal11.json"


@pytest.fixture(scope="module")
def drupal():
    if not os.environ.get("DDEV_SITENAME"):
        pytest.skip("Run Drupal acceptance tests inside DDEV")
    state = FIXTURE / "fixture-state.json"
    if not state.exists():
        if os.environ.get("DBGPILOT_REQUIRE_DRUPAL"):
            pytest.fail("Run ddev drupal-setup from the host before ddev drupal-test")
        pytest.skip("Optional Drupal fixture: run ddev drupal-setup")
    info = json.loads(state.read_text())
    assert info["fixture"] == "dbgpilot-drupal11" and info["drupal"] == "11.4.11"
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(json.dumps({"runtime": info, "scenarios": {}}, indent=2) + "\n")
    return info


def breakpoint_in(relative, statement):
    path = FIXTURE / relative
    assert path.exists(), "Drupal source is missing in the Python container; run ddev drupal-setup"
    matches = [number for number, line in enumerate(path.read_text().splitlines(), 1) if statement in line]
    assert len(matches) == 1, f"The pinned source no longer has one breakpoint statement: {statement}"
    return BreakpointSpec(str(path), matches[0])


def server():
    # Accept the engine from the separate Drupal container, retaining a loopback API.
    return Server(port=0, xdebug_host="0.0.0.0", path_mappings=[PathMapping(str(FIXTURE), "file:///var/www/html")])


def record(name, snapshot, **details):
    report = json.loads(REPORT.read_text())
    report["scenarios"][name] = {
        "passed": True,
        "session_id": snapshot["session_id"],
        "execution": snapshot["execution"],
        "frames": [{"file": frame["file"], "local_file": frame["local_file"],
                    "function": frame["function"]} for frame in snapshot["frames"]],
        **details,
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n")


async def login(page, drupal):
    await page.goto(drupal["test_url"] + "/user/login")
    await page.locator('input[name="name"]').fill("admin")
    await page.locator('input[name="pass"]').fill("dbgpilot-admin")
    await page.get_by_role("button", name="Log in", exact=True).click()
    response = await page.goto(drupal["test_url"] + "/node/add/page")
    assert response.status == 200, await page.locator("body").inner_text()
    assert await page.locator('input[name="title[0][value]"]').is_visible()


async def test_drupal_owned_setup_configuration_and_reconnect(browser_page, drupal):
    breakpoint = breakpoint_in(
        "web/core/lib/Drupal/Core/Entity/Controller/EntityViewController.php",
        "$page = $this->entityTypeManager",
    )
    setup = DebuggerSetup(config=FIXTURE / "dbgpilot.toml", launch=True, port=0,
                          xdebug_host="0.0.0.0")
    try:
        async with setup, setup.debugger(browser_page) as debugger:
            paused = await debugger.goto(
                drupal["test_url"] + drupal["node_path"], breakpoints=[breakpoint],
                expressions=["$_entity->label()"],
            )
            assert paused.snapshot["execution"]["local_file"] == breakpoint.file
            assert paused.snapshot["expressions"]["$_entity->label()"]["value"] == drupal["node_title"]
            await setup.client.aclose()
            async with Client(setup.url) as later:
                session = later.session(paused.session_id)
                assert (await session.info())["state"] == "break"
                await session.evaluate('$_entity->setTitle("DBGpilot setup example")')
                await session.detach()
            await paused.finished()
            assert await browser_page.get_by_role("heading", level=1).inner_text() == "DBGpilot setup example"
    finally:
        if setup.owns_server:
            await setup.shutdown(release_sessions=True)


async def test_drupal_core_snapshot_reconnect_mutation_and_unchanged_database(browser_page, drupal):
    breakpoint = breakpoint_in(
        "web/core/lib/Drupal/Core/Entity/Controller/EntityViewController.php",
        "$page = $this->entityTypeManager",
    )
    url = drupal["test_url"] + drupal["node_path"]
    changed = "DBGpilot changed this request"
    async with server() as pilot, Client(pilot.url) as first:
        async with PlaywrightDebugger(browser_page, first) as debugger:
            paused = await debugger.goto(
                url, breakpoints=[breakpoint], variables=["$_entity", "$view_mode"],
                expressions=["$_entity->id()", "$_entity->label()"], timeout=30,
            )
            snapshot = paused.snapshot
            assert snapshot["expressions"]["$_entity->label()"]["value"] == drupal["node_title"]
            assert snapshot["expressions"]["$_entity->id()"]["value"] == str(drupal["node_id"])
            assert snapshot["execution"]["local_file"] == breakpoint.file
            # Drupal executes the controller inside a render Fiber; Xdebug's
            # stack ends there rather than including the parent HttpKernel.
            assert any("{fiber:" in frame["function"] for frame in snapshot["frames"])
            assert any("/Render/Renderer.php" in frame["file"] for frame in snapshot["frames"])
            assert not paused.action.done()
            await first.aclose()
            async with Client(pilot.url) as later:
                session = paused.session(later)
                assert (await session.info())["state"] == "break"
                await session.evaluate("$_entity->setTitle(" + json.dumps(changed) + ")")
                await session.step_over()
                await session.detach()
            assert (await paused.finished()).status == 200
            assert await browser_page.get_by_role("heading", level=1).inner_text() == changed
            # The object changed in memory; no entity save was sent in this flow.
            await browser_page.goto(url)
            assert await browser_page.get_by_role("heading", level=1).inner_text() == drupal["node_title"]
            await browser_page.screenshot(path=str(REPORT.with_suffix(".png")), full_page=True)
            record("core_view", snapshot, rendered_title=changed, persisted_title=drupal["node_title"])


async def test_drupal_form_save_reconnect_mutation_and_database_persistence(browser_page, drupal):
    await login(browser_page, drupal)
    await browser_page.goto(drupal["test_url"] + "/node/add/page")
    proposed = "DBGpilot browser page " + uuid.uuid4().hex[:8]
    persisted = proposed + " changed in PHP"
    await browser_page.locator('input[name="title[0][value]"]').fill(proposed)
    breakpoint = breakpoint_in("web/core/modules/node/src/Form/NodeForm.php", "$node->save();")
    created_path = None
    try:
        async with server() as pilot, Client(pilot.url) as first:
            async with PlaywrightDebugger(browser_page, first) as debugger:
                paused = await debugger.capture(
                    lambda: browser_page.get_by_role("button", name="Save", exact=True).click(timeout=0),
                    url_pattern=lambda url: "/node/add/page" in url,
                    breakpoints=[breakpoint], variables=["$node", "$insert"],
                    expressions=["$node->label()", "$node->isNew()"], timeout=30,
                )
                snapshot = paused.snapshot
                assert snapshot["expressions"]["$node->label()"]["value"] == proposed
                assert snapshot["expressions"]["$node->isNew()"]["value"] is True
                assert snapshot["execution"]["local_file"] == breakpoint.file
                assert any("/Form/FormSubmitter.php" in frame["file"] for frame in snapshot["frames"])
                await first.aclose()
                async with Client(pilot.url) as later:
                    session = paused.session(later)
                    await session.evaluate("$node->setTitle(" + json.dumps(persisted) + ")")
                    await session.step_over()
                    node_id = (await session.evaluate("$node->id()"))["value"]
                    created_path = "/node/" + str(node_id)
                    await session.detach()
                await paused.finished()
                await browser_page.wait_for_url("**" + created_path)
                assert await browser_page.get_by_role("heading", level=1).inner_text() == persisted
                # A fresh request reads the saved entity from the real database.
                await browser_page.goto(drupal["test_url"] + created_path)
                assert await browser_page.get_by_role("heading", level=1).inner_text() == persisted
                assert snapshot["expressions"]["$node->label()"]["value"] == proposed
                record("form_save", snapshot, proposed_title=proposed, persisted_title=persisted, node_path=created_path)
    finally:
        if created_path:
            await browser_page.goto(drupal["test_url"] + created_path + "/delete")
            await browser_page.get_by_role("button", name="Delete", exact=True).click()


async def test_drupal_author_autocomplete_ajax_with_database_query(browser_page, drupal):
    await login(browser_page, drupal)
    author = browser_page.locator('input[name="uid[0][target_id]"]')
    # Expand its actual authoring-information details, including ancestor groups.
    await author.evaluate("""element => {
      for (let parent = element.parentElement; parent; parent = parent.parentElement) {
        if (parent.tagName === 'DETAILS') parent.open = true;
      }
    }""")
    await author.fill("")
    breakpoint = breakpoint_in(
        "web/core/modules/system/src/Controller/EntityAutocompleteController.php",
        "$matches = $this->matcher->getMatches",
    )
    async with server() as pilot, Client(pilot.url) as client:
        async with PlaywrightDebugger(browser_page, client) as debugger:
            paused = await debugger.capture(
                lambda: author.fill("adm"),
                url_pattern=lambda url: "/entity_reference_autocomplete/user/" in url,
                breakpoints=[breakpoint], variables=["$target_type", "$typed_string"], timeout=30,
            )
            snapshot = paused.snapshot
            assert snapshot["variables"]["$target_type"]["value"] == "user"
            assert snapshot["variables"]["$typed_string"]["value"] == "adm"
            # Typing finishes while the actual autocomplete HTTP request is paused.
            await paused.finished()
            session = paused.session()
            assert (await session.info())["state"] == "break"
            await session.set_value("$typed_string", "admin")
            await session.step_over()
            count = (await session.evaluate("count($matches)"))["value"]
            assert count >= 1
            await session.detach()
            option = browser_page.locator(".ui-autocomplete .ui-menu-item").filter(has_text="admin").first
            await option.wait_for(state="visible")
            record("author_autocomplete", snapshot, query="admin", result_count=count)

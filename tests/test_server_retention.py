"""Event collection should scale with events without rescanning session history."""

import asyncio
import base64

import pytest

from dbgpilot import RemoteError
from .helpers import Engine, xml
from .test_server import remote_session


class CountingRecords(dict):
    """Measure record visits rather than relying on wall-clock thresholds."""

    entries_visited = 0

    def items(self):
        for item in super().items():
            self.entries_visited += 1
            yield item


@pytest.mark.parametrize("with_closed_session", [False, True], ids=["no-history", "closed-history"])
async def test_ordinary_events_do_not_scan_session_records(monkeypatch, with_closed_session):
    async with remote_session() as (server, client, remote, engine):
        retired_engine = None
        try:
            if with_closed_session:
                retired_engine = await Engine.connect(server.controller, idekey="retired")
                retired = await client.wait_for_session(idekey="retired", timeout=2)
                await retired.close()
                assert (await retired.events(timeout=2))["closed"]
            records = CountingRecords(server._records)
            monkeypatch.setattr(server, "_records", records)
            for index in range(16):
                stream = xml("stream", type="stdout", encoding="base64")
                stream.text = base64.b64encode(f"line {index}".encode()).decode()
                await engine.send(stream)
                await engine.send(xml("notify", name=f"notice-{index}"))

            events, cursor = [], 0
            async with asyncio.timeout(5):
                while cursor < 32:
                    batch = await remote.events(after=cursor, timeout=2)
                    events.extend(batch["events"])
                    cursor = batch["cursor"]
            assert [event["sequence"] for event in events] == list(range(1, 33))
            assert [event["type"] for event in events] == ["StreamEvent", "NotificationEvent"] * 16
            assert records.entries_visited == 0, "Ordinary events must not rescan session history"
        finally:
            if retired_engine is not None:
                await retired_engine.close()


@pytest.mark.parametrize("limit", [0, 1, 3])
async def test_closing_sessions_prunes_oldest_records_and_preserves_live_sessions(limit):
    async with remote_session(server_options={"max_closed_sessions": limit}) as (server, client, live, _):
        engines, closed_ids = [], []
        try:
            for index in range(limit + 2):
                engine = await Engine.connect(server.controller, idekey=f"retired-{index}")
                engines.append(engine)
                remote = await client.wait_for_session(idekey=f"retired-{index}", timeout=2)
                await remote.close()
                closed_ids.append(remote.id)
                # Fence the asynchronous ClosedEvent before checking public inventory.
                async with asyncio.timeout(5), server._condition:
                    await server._condition.wait_for(lambda: (
                        remote.id not in server._records if limit == 0
                        else server._records[remote.id].closed_at is not None
                    ))
                retained = closed_ids[-limit:] if limit else []
                inventory = await client.sessions()
                assert {item["session_id"] for item in inventory} == {live.id, *retained}
                assert {item["session_id"] for item in inventory if item["closed"]} == set(retained)

            for identifier in closed_ids[:len(closed_ids) - limit]:
                with pytest.raises(RemoteError) as caught:
                    await client.session(identifier).info()
                assert caught.value.code == -32001
            assert not (await live.info())["closed"]
            for identifier in retained:
                assert (await client.session(identifier).events(timeout=0))["events"][-1]["type"] == "ClosedEvent"
        finally:
            await asyncio.gather(*(engine.close() for engine in engines))

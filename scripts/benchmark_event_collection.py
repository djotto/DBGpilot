"""Measure the event collector in isolation, excluding sockets and PHP startup.

Run on each revision with identical arguments, for example:
ddev poetry run python scripts/benchmark_event_collection.py --output test-results/events.json
"""

import argparse
import asyncio
from collections import deque
import hashlib
from itertools import chain, repeat
import json
from pathlib import Path
import platform
import statistics
import time

from dbgpilot import ConnectionClosed, Server, StreamEvent
from dbgpilot.models import ClosedEvent
from dbgpilot.server import _Record
import dbgpilot.server as server_module


class BufferedEvents:
    """Provide ready events so the measured work is collection and retention."""

    def __init__(self, count):
        self.events = chain(
            repeat(StreamEvent("stdout", b"diagnostic output\n"), count),
            [ClosedEvent(ConnectionClosed())],
        )

    async def next_event(self):
        return next(self.events)


async def sample(event_count, live_count, closed_count):
    server = Server(port=0, xdebug_port=0, max_closed_sessions=128)
    server._loop = asyncio.get_running_loop()
    for index in range(closed_count):
        server._records[f"closed-{index}"] = _Record(None, deque(), closed_at=float(index))
    for index in range(live_count - 1):
        server._records[f"live-{index}"] = _Record(None, deque())
    record = _Record(BufferedEvents(event_count), deque(maxlen=server.event_history))
    server._records["measured"] = record
    started = time.perf_counter()
    await server._collect_events(record)
    elapsed = time.perf_counter() - started
    assert record.sequence == event_count + 1
    assert record.events[-1]["type"] == "ClosedEvent"
    assert record.closed_at is not None
    assert sum(item.closed_at is not None for item in server._records.values()) == min(closed_count + 1, 128)
    return elapsed


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=int, default=20000)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.events < 1 or args.repeats < 1:
        parser.error("events and repeats must be positive")
    scenarios = [(1, 0), (1, 128), (64, 0), (64, 128)]
    samples = {scenario: [] for scenario in scenarios}
    for live_count, closed_count in scenarios:
        await sample(args.events, live_count, closed_count)  # Unmeasured warm-up.
    for iteration in range(args.repeats):
        # Rotate case order to reduce systematic timing drift between cases.
        order = scenarios[iteration % len(scenarios):] + scenarios[:iteration % len(scenarios)]
        for live_count, closed_count in order:
            samples[(live_count, closed_count)].append(await sample(args.events, live_count, closed_count))
    results = []
    for (live_count, closed_count), timings in samples.items():
        median = statistics.median(timings)
        results.append({
            "live_sessions": live_count, "closed_sessions": closed_count,
            "seconds": timings, "median_seconds": median,
            "median_events_per_second": args.events / median,
        })
    report = {
        "scope": "Event collector only; prebuffered stdout events followed by one close; no HTTP or PHP",
        "python": platform.python_version(), "platform": platform.platform(),
        "server_sha256": hashlib.sha256(Path(server_module.__file__).read_bytes()).hexdigest(),
        "events_per_sample": args.events, "repeats": args.repeats,
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    for result in results:
        print(
            f"live={result['live_sessions']} closed={result['closed_sessions']}: "
            f"{result['median_seconds']:.4f}s median, "
            f"{result['median_events_per_second']:,.0f} events/s",
            flush=True,
        )
    print(f"Saved {args.output}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())

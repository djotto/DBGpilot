"""Internal FIFO notifications that never consume data in a background task."""

import asyncio
from collections import deque


class RetainedQueue:
    """A synchronous FIFO with an asyncio event signaling available items."""

    def __init__(self, maxsize=0):
        self.maxsize = maxsize
        self._items = deque()
        self.available = asyncio.Event()

    def empty(self):
        """Return whether the queue contains no items."""
        return not self._items

    def full(self):
        """Return whether the configured positive capacity has been reached."""
        return self.maxsize > 0 and len(self._items) >= self.maxsize

    def qsize(self):
        """Return the number of retained items."""
        return len(self._items)

    def put_nowait(self, value):
        """Append an item and signal availability, or raise asyncio.QueueFull."""
        if self.full():
            raise asyncio.QueueFull
        self._items.append(value)
        self.available.set()

    def get_nowait(self):
        """Remove the oldest item, or raise asyncio.QueueEmpty if none remain."""
        if self.empty():
            raise asyncio.QueueEmpty
        value = self._items.popleft()
        if self.empty():
            self.available.clear()
        return value

    def discard(self, value):
        """Remove the first matching item if present and update availability."""
        try:
            self._items.remove(value)
        except ValueError:
            pass
        if self.empty():
            self.available.clear()

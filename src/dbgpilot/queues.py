"""Internal FIFO notifications that never consume data in a background task."""

import asyncio
from collections import deque


class RetainedQueue:
    def __init__(self, maxsize=0):
        self.maxsize = maxsize
        self._items = deque()
        self.available = asyncio.Event()

    def empty(self):
        return not self._items

    def full(self):
        return self.maxsize > 0 and len(self._items) >= self.maxsize

    def qsize(self):
        return len(self._items)

    def put_nowait(self, value):
        if self.full():
            raise asyncio.QueueFull
        self._items.append(value)
        self.available.set()

    def get_nowait(self):
        if self.empty():
            raise asyncio.QueueEmpty
        value = self._items.popleft()
        if self.empty():
            self.available.clear()
        return value

    def discard(self, value):
        try:
            self._items.remove(value)
        except ValueError:
            pass
        if self.empty():
            self.available.clear()

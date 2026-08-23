"""FIFO admission control for model inference (Phase 4).

When more students are asking than the tier has slots, a queued student who is told
"you're 2nd in line" is a better outcome than five students sharing a box that swaps
itself to death. A semaphore alone would do the throttling, but it wakes waiters in
arbitrary order and cannot tell anyone their position - so this is a plain lock plus
an explicit ticket queue.

Tier 1 leans on this hardest: conceptual questions cannot be handed off to templates,
so a single-slot box will genuinely queue.
"""

import threading
import time
from collections import deque

__all__ = ["InferenceQueue", "QueueTimeout"]


class QueueTimeout(Exception):
    """Raised when a ticket waited longer than the caller was willing to wait."""


class _Ticket(object):
    __slots__ = ("event", "queued_at", "cancelled")

    def __init__(self):
        self.event = threading.Event()
        self.queued_at = time.time()
        self.cancelled = False


class InferenceQueue(object):
    """Bounded, strictly first-come-first-served access to the model.

    Usage:

        with q.slot(on_wait=lambda pos: notify(pos)) as wait_seconds:
            ...call the model...

    `on_wait` fires once with the caller's 1-based queue position, and only when the
    caller actually has to wait, so the client can show an honest wait indicator
    instead of hanging silently.
    """

    def __init__(self, slots):
        if slots < 1:
            raise ValueError("slots must be at least 1")
        self.slots = slots
        self._lock = threading.Lock()
        self._active = 0
        self._waiting = deque()
        self._total_waits = 0
        self._total_wait_seconds = 0.0
        self._max_wait_seconds = 0.0

    # -- introspection, for the health endpoint --

    @property
    def depth(self):
        """How many students are waiting right now (not counting those being served)."""
        with self._lock:
            return len(self._waiting)

    @property
    def active(self):
        with self._lock:
            return self._active

    def stats(self):
        with self._lock:
            avg = (self._total_wait_seconds / self._total_waits) if self._total_waits else 0.0
            return {"slots": self.slots, "active": self._active,
                    "waiting": len(self._waiting), "waits": self._total_waits,
                    "avg_wait_seconds": round(avg, 2),
                    "max_wait_seconds": round(self._max_wait_seconds, 2)}

    # -- core --

    def acquire(self, timeout=None, on_wait=None):
        """Block until a slot is free. Returns seconds spent waiting."""
        with self._lock:
            if self._active < self.slots and not self._waiting:
                self._active += 1
                return 0.0
            ticket = _Ticket()
            self._waiting.append(ticket)
            position = len(self._waiting)

        if on_wait:
            try:
                on_wait(position)
            except Exception:                    # noqa: BLE001 - a UI callback must
                pass                             # never break admission control

        if not ticket.event.wait(timeout):
            with self._lock:
                if ticket in self._waiting:
                    ticket.cancelled = True
                    self._waiting.remove(ticket)
                    raise QueueTimeout("waited %s seconds without reaching a slot"
                                       % timeout)
            # The slot was handed over in the moment we timed out; take it rather than
            # leaking it, since release() has already counted this ticket as active.
        waited = time.time() - ticket.queued_at
        with self._lock:
            self._total_waits += 1
            self._total_wait_seconds += waited
            self._max_wait_seconds = max(self._max_wait_seconds, waited)
        return waited

    def release(self):
        with self._lock:
            while self._waiting:
                nxt = self._waiting.popleft()
                if not nxt.cancelled:
                    nxt.event.set()              # hand the slot straight over
                    return
            self._active -= 1

    def slot(self, timeout=None, on_wait=None):
        return _SlotContext(self, timeout, on_wait)


class _SlotContext(object):
    __slots__ = ("q", "timeout", "on_wait", "waited")

    def __init__(self, q, timeout, on_wait):
        self.q = q
        self.timeout = timeout
        self.on_wait = on_wait
        self.waited = 0.0

    def __enter__(self):
        self.waited = self.q.acquire(self.timeout, self.on_wait)
        return self.waited

    def __exit__(self, *exc):
        self.q.release()
        return False

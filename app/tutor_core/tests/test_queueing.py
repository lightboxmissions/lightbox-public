"""Queue tests: order, capacity, honest wait reporting, and no leaked slots.

A leaked slot is the worst outcome here - the box would slowly stop serving anyone
with no error to point at, which is exactly the kind of failure a volunteer cannot
diagnose in a school with no internet.
"""

import threading
import time
import unittest

from tutor_core.queueing import InferenceQueue, QueueTimeout


class TestInferenceQueue(unittest.TestCase):

    def test_capacity_is_never_exceeded(self):
        q = InferenceQueue(2)
        peak = [0]
        active = [0]
        lock = threading.Lock()

        def work():
            with q.slot():
                with lock:
                    active[0] += 1
                    peak[0] = max(peak[0], active[0])
                time.sleep(0.05)
                with lock:
                    active[0] -= 1

        threads = [threading.Thread(target=work) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(peak[0], 2)
        self.assertEqual(q.active, 0)
        self.assertEqual(q.depth, 0)

    def test_first_come_first_served(self):
        q = InferenceQueue(1)
        order = []

        def work(i):
            with q.slot():
                order.append(i)
                time.sleep(0.03)

        threads = []
        for i in range(5):
            t = threading.Thread(target=work, args=(i,))
            t.start()
            threads.append(t)
            time.sleep(0.01)          # stagger so arrival order is unambiguous
        for t in threads:
            t.join()
        self.assertEqual(order, [0, 1, 2, 3, 4])

    def test_position_reported_only_when_actually_waiting(self):
        q = InferenceQueue(1)
        seen = {}

        def work(i):
            with q.slot(on_wait=lambda p: seen.__setitem__(i, p)):
                time.sleep(0.04)

        threads = []
        for i in range(3):
            t = threading.Thread(target=work, args=(i,))
            t.start()
            threads.append(t)
            time.sleep(0.01)
        for t in threads:
            t.join()
        self.assertNotIn(0, seen)     # served immediately, no wait indicator
        self.assertEqual(seen[1], 1)
        self.assertEqual(seen[2], 2)

    def test_timeout_releases_the_ticket(self):
        q = InferenceQueue(1)
        q.acquire()
        with self.assertRaises(QueueTimeout):
            q.acquire(timeout=0.05)
        self.assertEqual(q.depth, 0)
        q.release()
        self.assertEqual(q.active, 0)

    def test_exception_inside_the_slot_still_releases_it(self):
        q = InferenceQueue(1)
        with self.assertRaises(ValueError):
            with q.slot():
                raise ValueError("model blew up")
        self.assertEqual(q.active, 0)
        with q.slot() as waited:      # the slot must still be usable
            self.assertEqual(waited, 0.0)

    def test_callback_failure_does_not_break_admission(self):
        q = InferenceQueue(1)
        q.acquire()

        def bad_callback(_pos):
            raise RuntimeError("client disconnected")

        done = []

        def work():
            with q.slot(on_wait=bad_callback):
                done.append(True)

        t = threading.Thread(target=work)
        t.start()
        time.sleep(0.05)
        q.release()
        t.join(timeout=1.0)
        self.assertEqual(done, [True])

    def test_stats_report_waits(self):
        q = InferenceQueue(1)
        q.acquire()
        t = threading.Thread(target=lambda: q.slot().__enter__())
        t.start()
        time.sleep(0.05)
        self.assertEqual(q.stats()["waiting"], 1)
        q.release()
        t.join(timeout=1.0)
        self.assertGreaterEqual(q.stats()["waits"], 1)
        self.assertGreater(q.stats()["max_wait_seconds"], 0.0)

    def test_rejects_zero_slots(self):
        with self.assertRaises(ValueError):
            InferenceQueue(0)


if __name__ == "__main__":
    unittest.main()

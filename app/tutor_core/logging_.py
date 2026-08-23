"""Local-only logging (Phase 7).

Never leaves the device. No network calls, no telemetry, no identifiers beyond what a
volunteer needs during a check-in: is this device's tier right, is the model choice
holding up, how often did the verifier have to correct the model, and how long are
students waiting.

JSONL so a volunteer can read it with a text editor and a script can aggregate it.
Rotated by size, because a donated laptop may not come back for a year.
"""

import json
import os
import threading
import time

__all__ = ["TutorLog"]

MAX_BYTES = 2 * 1024 * 1024        # ~10k answers; a year of one classroom
KEEP = 2


class TutorLog(object):
    """Append-only local log. Thread-safe; a logging failure never breaks an answer."""

    def __init__(self, path, hardware=None):
        self.path = path
        self._lock = threading.Lock()
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        if hardware is not None:
            self.write("startup", hardware=hardware.as_dict())

    def _rotate_if_needed(self):
        try:
            if os.path.getsize(self.path) < MAX_BYTES:
                return
        except OSError:
            return
        for i in range(KEEP - 1, 0, -1):
            src, dst = "%s.%d" % (self.path, i), "%s.%d" % (self.path, i + 1)
            if os.path.exists(src):
                os.replace(src, dst)
        os.replace(self.path, self.path + ".1")

    def write(self, event, **fields):
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event}
        rec.update(fields)
        line = json.dumps(rec, ensure_ascii=False)
        try:
            with self._lock:
                self._rotate_if_needed()
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except OSError:
            pass                        # a full disk must not cost a student an answer

    def answer(self, tier, kind, seconds, source, corrections=0, queue_wait=0.0,
               queue_depth=0, expression=None):
        """One answered question.

        `kind` is computational/conceptual and `source` is template/engine/model - the
        two fields a volunteer needs to see whether the tier thresholds and the
        computational/conceptual balance match what this device actually meets.
        """
        self.write("answer", tier=tier, kind=kind, seconds=round(seconds, 2),
                   source=source, corrections=corrections,
                   queue_wait=round(queue_wait, 2), queue_depth=queue_depth,
                   expression=expression)

    def correction(self, kind, expression, stated, correct):
        """The verifier caught the model stating a wrong number. Logged separately so
        the rate is countable without parsing every answer record."""
        self.write("correction", kind=kind, expression=expression,
                   stated=stated, correct=correct)

    def warning(self, message, **fields):
        self.write("warning", message=message, **fields)


def summarize(path):
    """Aggregate a log for a device check-in. Returns counts a volunteer can act on."""
    stats = {"answers": 0, "by_kind": {}, "by_source": {}, "corrections": 0,
             "avg_seconds": {}, "max_queue_wait": 0.0, "warnings": []}
    totals = {}
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return stats
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        ev = rec.get("event")
        if ev == "answer":
            kind, src = rec.get("kind", "?"), rec.get("source", "?")
            stats["answers"] += 1
            stats["by_kind"][kind] = stats["by_kind"].get(kind, 0) + 1
            stats["by_source"][src] = stats["by_source"].get(src, 0) + 1
            stats["corrections"] += rec.get("corrections", 0)
            n, s = totals.get(kind, (0, 0.0))
            totals[kind] = (n + 1, s + rec.get("seconds", 0.0))
            stats["max_queue_wait"] = max(stats["max_queue_wait"],
                                          rec.get("queue_wait", 0.0))
        elif ev == "warning":
            stats["warnings"].append(rec.get("message", ""))
    for kind, (n, s) in totals.items():
        stats["avg_seconds"][kind] = round(s / n, 2) if n else 0.0
    return stats

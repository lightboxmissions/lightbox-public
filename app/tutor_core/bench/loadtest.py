"""Phase 6 load test: concurrent student sessions against a real llama-server.

Answers the go/no-go question the spec asks, which is not "does it work" but "does a
student ever wait so long that the tool is unusable". Reports the slowest answer, not
just the average - the average hides the student who waited three minutes.

Uses the realistic mixed question load. An all-computational run would understate load
badly, because templates answer most of those with no inference at all.

    python3 -m tutor_core.bench.loadtest --students 5
    python3 -m tutor_core.bench.loadtest --students 5 --force-tier 1   # weak-box config

To approximate a 2012 dual-core on better hardware, pin the tier AND restrict the CPU:
    taskset -c 0,1 python3 -m tutor_core.bench.loadtest --students 5 --force-tier 1
"""

import argparse
import random
import threading
import time

from ..service import Config, build_tutor
from . import questions


def run(config, students, rounds, think_time, timeout):
    tutor = build_tutor(config)
    hw = tutor.hardware
    print("tier %d, %d slot(s), ctx %d, model %s%s"
          % (hw.tier, hw.max_parallel_slots, hw.ctx_size, config.model,
             (", %.2f tok/s" % hw.tokens_per_sec) if hw.tokens_per_sec else ""))
    print("%d students x %d questions, mixed computational/conceptual\n"
          % (students, rounds))

    results = []
    lock = threading.Lock()
    started = time.time()

    def session(sid):
        rng = random.Random(sid)
        for i in range(rounds):
            q = rng.choice(questions.MIXED)
            t0 = time.time()
            a = tutor.ask(q, timeout=timeout)
            with lock:
                results.append({"student": sid, "q": q, "kind": a.kind,
                                "source": a.source, "seconds": time.time() - t0,
                                "queue_wait": a.queue_wait, "error": a.error})
            if think_time:
                time.sleep(rng.uniform(0, think_time))

    threads = [threading.Thread(target=session, args=(i,)) for i in range(students)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.time() - started

    by_kind = {}
    for r in results:
        by_kind.setdefault(r["kind"], []).append(r)

    def pct(xs, p):
        if not xs:
            return 0.0
        xs = sorted(xs)
        return xs[min(len(xs) - 1, int(len(xs) * p))]

    print("%-14s %5s %8s %8s %8s %8s" % ("kind", "n", "avg", "p50", "p95", "max"))
    for kind, rows in sorted(by_kind.items()):
        secs = [r["seconds"] for r in rows]
        print("%-14s %5d %7.1fs %7.1fs %7.1fs %7.1fs"
              % (kind, len(rows), sum(secs) / len(secs), pct(secs, 0.5),
                 pct(secs, 0.95), max(secs)))

    waits = [r["queue_wait"] for r in results]
    errors = [r for r in results if r["error"]]
    sources = {}
    for r in results:
        sources[r["source"]] = sources.get(r["source"], 0) + 1

    print("\nanswers by source: %s"
          % ", ".join("%s=%d" % kv for kv in sorted(sources.items())))
    print("queue wait: avg %.1fs, max %.1fs" % (sum(waits) / len(waits), max(waits)))
    print("wall clock: %.1fs for %d answers (%.2f answers/sec)"
          % (wall, len(results), len(results) / wall))
    if errors:
        print("\n%d ERROR(S) - these are hangs or model failures, the thing this test "
              "exists to catch:" % len(errors))
        for e in errors[:10]:
            print("  student %d, %r: %s" % (e["student"], e["q"][:40], e["error"]))
    worst = max(results, key=lambda r: r["seconds"])
    print("\nslowest answer: %.1fs (%s, %s) %r"
          % (worst["seconds"], worst["kind"], worst["source"], worst["q"][:50]))
    return 1 if errors else 0


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--llama-url", default="http://127.0.0.1:8080/v1/chat/completions")
    p.add_argument("--model", default="qwen2.5-3b-instruct-q4_k_m.gguf")
    p.add_argument("--students", type=int, default=5)
    p.add_argument("--rounds", type=int, default=3)
    p.add_argument("--think-time", type=float, default=0.0,
                   help="max seconds a student pauses between questions")
    p.add_argument("--timeout", type=float, default=600.0)
    p.add_argument("--force-tier", type=int, default=0, choices=[0, 1, 2, 3])
    p.add_argument("--log", default="data/tutor_loadtest.jsonl")
    a = p.parse_args(argv)
    return run(Config(llama_url=a.llama_url, model=a.model, log_path=a.log,
                      force_tier=a.force_tier),
               a.students, a.rounds, a.think_time, a.timeout)


if __name__ == "__main__":
    raise SystemExit(main())

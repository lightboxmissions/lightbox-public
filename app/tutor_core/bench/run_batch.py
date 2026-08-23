"""Phase 6 integration run against a real llama-server.

Two things happen here that unit tests cannot do:

  1. Every computational question is graded automatically. The pass bar is ZERO wrong
     final numeric answers - not a percentage.
  2. Every conceptual answer is written to a review file, because there is no
     programmatic check for whether an explanation is accurate and age-appropriate.
     A human reads that file; the script only flags what needs reading.

Usage (on the box, where llama-server is running):

    python3 -m tutor_core.bench.run_batch --review /tmp/review.md
    python3 -m tutor_core.bench.run_batch --model phi-4-mini-instruct-q4_k_m.gguf \
        --review /tmp/review_phi.md          # same set, other model, to compare
"""

import argparse
import time

from .. import verify
from ..router import COMPUTATIONAL as KIND_COMPUTATIONAL
from ..service import Config, build_tutor
from . import questions


def _states(answer_text, expected):
    """Does the answer actually contain the expected result?

    Substring is the right test here: the tutor is allowed to say "15 + 2 = 17. Start
    at 15..." but must not omit or contradict the number.
    """
    return expected in answer_text


def run(config, review_path, limit=0):
    tutor = build_tutor(config)
    hw = tutor.hardware
    print("tier %d, %d slot(s), model %s%s"
          % (hw.tier, hw.max_parallel_slots, config.model,
             (", %.2f tok/s" % hw.tokens_per_sec) if hw.tokens_per_sec else ""))

    comp = questions.COMPUTATIONAL[:limit] if limit else questions.COMPUTATIONAL
    conc = questions.CONCEPTUAL[:limit] if limit else questions.CONCEPTUAL

    wrong, unverified, timings = [], [], {"computational": [], "conceptual": []}
    corrections = 0
    review = ["# Conceptual answers needing human review",
              "",
              "Model: `%s`  |  tier %d  |  generated %s"
              % (config.model, hw.tier, time.strftime("%Y-%m-%d %H:%M")),
              "",
              "Read each answer for accuracy and age-appropriateness. There is no",
              "automated check for these - that is a deliberate limit of the design.",
              ""]

    print("\n-- computational (%d) --" % len(comp))
    for q, expected in comp:
        a = tutor.ask(q)
        timings["computational"].append(a.seconds)
        corrections += len(a.corrections)
        leftover = verify.check(a.text)
        ok = _states(a.text, expected) and not leftover and a.kind == KIND_COMPUTATIONAL
        if not ok:
            wrong.append((q, expected, a))
        if leftover:
            unverified.append((q, a, leftover))
        print("  %s %-42s %-8s %5.1fs  %s"
              % ("ok " if ok else "BAD", q[:42], a.source, a.seconds,
                 a.text[:60].replace("\n", " ")))

    print("\n-- conceptual (%d) --" % len(conc))
    for q in conc:
        a = tutor.ask(q)
        timings["conceptual"].append(a.seconds)
        corrections += len(a.corrections)
        leftover = verify.check(a.text)
        if leftover:
            unverified.append((q, a, leftover))
        print("  %-42s %5.1fs  %d fix  %s"
              % (q[:42], a.seconds, len(a.corrections),
                 a.text[:50].replace("\n", " ")))
        review.append("## %s" % q)
        review.append("")
        review.append(a.text or "_(no answer - model error: %s)_" % a.error)
        if a.corrections:
            review.append("")
            review.append("> Verifier corrected %d wrong number(s) before this was "
                          "shown: %s" % (len(a.corrections),
                                         ", ".join("%s = %s (model said %s)"
                                                   % (c.expression, c.correct, c.stated)
                                                   for c in a.corrections)))
        review.append("")
        review.append("- [ ] accurate    - [ ] age-appropriate    - [ ] clear")
        review.append("")

    with open(review_path, "w", encoding="utf-8") as f:
        f.write("\n".join(review))

    def avg(xs):
        return sum(xs) / len(xs) if xs else 0.0

    print("\n" + "=" * 62)
    print("computational: %d, avg %.1fs" % (len(comp), avg(timings["computational"])))
    print("conceptual:    %d, avg %.1fs" % (len(conc), avg(timings["conceptual"])))
    print("verifier corrected %d wrong number(s) written by the model" % corrections)
    print("review file: %s (%d answers need a human)" % (review_path, len(conc)))

    if unverified:
        print("\nFAIL: %d answer(s) still contain a wrong equation AFTER verification "
              "- this is a bug in verify.py, not a model problem:" % len(unverified))
        for q, a, fixes in unverified:
            print("  %s -> %s" % (q, [f.as_dict() for f in fixes]))
    if wrong:
        print("\nFAIL: %d computational answer(s) did not state the correct result:"
              % len(wrong))
        for q, expected, a in wrong:
            print("  %-40s want %-8s got: %s" % (q, expected, a.text[:70]))
    if not wrong and not unverified:
        print("\nPASS: zero incorrect final numeric answers.")
    return 1 if (wrong or unverified) else 0


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--llama-url", default="http://127.0.0.1:8080/v1/chat/completions")
    p.add_argument("--model", default="qwen2.5-3b-instruct-q4_k_m.gguf")
    p.add_argument("--review", default="conceptual_review.md")
    p.add_argument("--log", default="data/tutor_bench.jsonl")
    p.add_argument("--limit", type=int, default=0, help="first N of each set")
    p.add_argument("--force-tier", type=int, default=0, choices=[0, 1, 2, 3])
    p.add_argument("--no-templates", action="store_true",
                   help="force every computational question through the model")
    a = p.parse_args(argv)
    return run(Config(llama_url=a.llama_url, model=a.model, log_path=a.log,
                      force_tier=a.force_tier, use_templates=not a.no_templates),
               a.review, a.limit)


if __name__ == "__main__":
    raise SystemExit(main())

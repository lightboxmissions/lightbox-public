# tutor_core

Offline math tutoring pipeline for LightBox. Pure standard library, no pip, no network
calls except to a local `llama-server`.

## The one rule

**The LLM never has final authority over arithmetic.**

- A **computational** question ("what's 15+2") gets its number from `matheng`, a
  deterministic evaluator, *before* any model is involved. Language wraps a
  pre-verified result — never the reverse.
- A **conceptual** question ("why do we carry the 1") is real language work and goes
  straight to the model, because there is no single right answer to compute against.
  Any arithmetic the model uses *inside* that explanation is still checked.
- Model output is **buffered, verified, then sent**. A student never sees an
  unverified number. This costs the appearance of streaming — the UI must show a real
  "thinking" indicator, especially on Tier 1.

## Modules

| file | phase | what it does |
|---|---|---|
| `hardware.py` | 1 | tier detection + startup micro-benchmark |
| `router.py` | 2 | computational vs conceptual |
| `matheng.py` | 2a | deterministic evaluator — the accuracy backbone |
| `templates.py` | 2b | zero-inference explanations, computational only |
| `queueing.py` | 4 | FIFO admission control with honest wait reporting |
| `verify.py` | — | scans model output, corrects wrong numbers |
| `logging_.py` | 7 | local-only JSONL logging |
| `pipeline.py` | 5 | the glue: `Tutor.ask()` |
| `service.py` | 5 | HTTP layer: `/api/tutor`, `/api/health` |
| `bench/` | 6 | real-model batch, load test, review harness |

Nothing outside `hardware.py` knows what CPU it is on; nothing outside `service.py`
knows which model is running.

## Tiers

| tier | rule | slots | ctx/slot |
|---|---|---|---|
| 1 weak | ≤2 physical cores, or <6GB RAM, or no AVX2 | 1 | 1024 |
| 2 mid | anything not disqualified and not clearly strong | 3 | 2048 |
| 3 strong | ≥4 physical cores **and** ≥12GB RAM | 5 | 4096 |

The spec's three descriptions leave a gap (a 3-core/8GB machine matches neither mid nor
strong), so anything not disqualified into Tier 1 and not clearly Tier 3 lands in
Tier 2 — the conservative middle, never a promotion.

Physical cores, not hyperthreads: two threads on one 2012 core do not make a machine
able to serve two students. Where physical-core data is unavailable, the logical count
is halved so an unknown machine tiers *down*.

**Tier 1 is not "the tier that avoids the model."** Conceptual questions need real
inference on every tier. Tier 1's job is to run the model conservatively — one slot,
small context — and let the queue absorb the rest.

The startup micro-benchmark exists because specs on paper lie: thermal throttling, a
background updater, or a swapping 4GB box all look fine to the probes. It measures real
tokens/sec and warns when the machine is slower than its tier expects. A failed
benchmark is never fatal.

## Usage

```python
from tutor_core.service import Config, build_tutor

TUTOR = build_tutor(Config(llama_url="http://127.0.0.1:8080/v1/chat/completions",
                           model="qwen2.5-3b-instruct-q4_k_m.gguf"))

answer = TUTOR.ask("why do we carry the 1", context=lesson_note)
answer.text          # verified text
answer.kind          # computational | conceptual
answer.source        # template | model | engine
answer.corrections   # numbers the verifier had to fix
```

Standalone:

```sh
python3 -m tutor_core.service --port 8091
curl -s localhost:8091/api/health
curl -s localhost:8091/api/tutor -d '{"question":"what is 15+2"}'
```

## Changing the model

`Config.model` and nothing else. The two candidates are Qwen2.5-3B (currently
deployed, ~1.9GB) and Phi-4-mini (stronger small-model math benchmarks, ~2.5GB, 3.8B
params so slower per token on the same CPU). Which one ships is a Phase 6 measurement,
not an assumption — run `bench/run_batch.py` with each and compare.

## Testing (Phase 6)

```sh
python3 -m unittest discover -s tutor_core/tests -t .        # 90 tests, no model needed
python3 -m tutor_core.bench.run_batch --review review.md     # real model, graded
python3 -m tutor_core.bench.loadtest --students 5            # concurrency
python3 -m tutor_core.bench.loadtest --students 5 --force-tier 1
```

`run_batch` grades every computational question automatically — the bar is **zero**
wrong final numeric answers, not a percentage — and writes every conceptual answer to a
markdown file with checkboxes for a teacher to sign off. There is no automated check
for whether an explanation is accurate and age-appropriate; that limit is deliberate.

To approximate a 2012 dual-core on better hardware:
`taskset -c 0,1 python3 -m tutor_core.bench.loadtest --students 5 --force-tier 1`

## Deliberate non-goals

- No per-device tuning beyond the three coarse tiers.
- No mid-generation tool-calling (one extra inference round trip, too slow here).
- No remote telemetry. `logging_.py` makes no network calls at all.
- No second model unless Tier 1 testing under realistic mixed load proves one is
  needed. `Config.model` makes that a config swap, not a rewrite.
- No attempt to verify conceptual explanations beyond internal numeric consistency.
  Full conceptual accuracy rests on model quality plus human spot-review.

## Reading the logs

```sh
python3 -c "from tutor_core.logging_ import summarize; print(summarize('data/tutor_log.jsonl'))"
```

Shows answer counts by kind and source, average seconds per kind, how often the
verifier caught the model stating a wrong number, and the worst queue wait — the four
things that say whether the tier thresholds, the model choice, and the
computational/conceptual balance suit this device pool.

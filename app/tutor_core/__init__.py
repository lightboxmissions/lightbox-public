"""tutor_core - offline math tutoring pipeline for Lunis.

Accuracy first, then reliability, then speed, then concurrency. The LLM never has
final authority over arithmetic: computational questions get their number from
`matheng`, and any number the model writes is cross-checked before a student sees it.

    hardware.py   tier detection + startup micro-benchmark      (Phase 1)
    router.py     computational vs conceptual                   (Phase 2)
    matheng.py    deterministic evaluator, the accuracy backbone(Phase 2a)
    templates.py  zero-inference explanations, computational    (Phase 2b)
    queueing.py   FIFO admission control                        (Phase 4)
    verify.py     scan model output, correct wrong numbers
    logging_.py   local-only logging                            (Phase 7)
    pipeline.py   the glue

Pure standard library, no network calls except to a local llama-server.
"""

from .hardware import detect, benchmark, HardwareConfig, TIER_WEAK, TIER_MID, TIER_STRONG
from .logging_ import TutorLog
from .matheng import MathError, Value, evaluate, solve
from .pipeline import Answer, Tutor
from .queueing import InferenceQueue, QueueTimeout
from .router import COMPUTATIONAL, CONCEPTUAL, classify

__all__ = ["detect", "benchmark", "HardwareConfig", "TIER_WEAK", "TIER_MID",
           "TIER_STRONG", "TutorLog", "MathError", "Value", "evaluate", "solve",
           "Answer", "Tutor", "InferenceQueue", "QueueTimeout", "COMPUTATIONAL",
           "CONCEPTUAL", "classify"]

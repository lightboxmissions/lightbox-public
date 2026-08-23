"""The tutor pipeline: classify, answer, verify (Phase 5 core).

    computational -> deterministic engine computes the number FIRST
                     -> template renders it with no inference at all, or
                     -> model writes an explanation around the pre-verified number
    conceptual    -> model explains directly
                     -> numeric examples inside the explanation get checked anyway

Model output is buffered, verified, and only then returned. A student never sees an
unverified number, which is the whole point of the architecture - it costs the
appearance of streaming, so the caller should show a real "thinking" indicator.

The model is injected as a plain callable, so this module has no idea which model is
running and no dependency on the web layer. Swapping Qwen for Phi-4-mini is a config
change here, not a code change.
"""

import re
import time

from . import matheng, router, templates, verify
from .queueing import InferenceQueue

__all__ = ["Answer", "Tutor"]

WRAP_SYS = (
    "You are a kind math tutor for a child. The correct answer has ALREADY been worked "
    "out for you and is given below - it is correct, and you must use exactly that "
    "number. Do not recompute it and do not give any other number as the answer. "
    "Explain in 1 to 3 short, simple sentences HOW to get there, so the child "
    "understands the method. Write math in plain text like 3 x 4 = 12, never LaTeX.")

COMPUTE_SYS = (
    "You are a kind math tutor for a child. Work the problem out carefully step by "
    "step, then give the answer in 1 to 3 short, simple sentences. Write math in plain "
    "text like 3 x 4 = 12, never LaTeX.")

CONCEPT_SYS = (
    "You are a kind math tutor for a child (age 6 to 13). Explain the idea the child "
    "is asking about in 2 to 4 short, simple sentences. Use one concrete everyday "
    "example. Be warm and encouraging. Any arithmetic you use in an example must be "
    "correct. Write math in plain text like 3 x 4 = 12, never LaTeX.")

SOURCE_TEMPLATE = "template"
SOURCE_MODEL = "model"
SOURCE_ENGINE = "engine"


class Answer(object):
    """What the API layer returns to a student."""

    __slots__ = ("text", "kind", "source", "value", "expression", "corrections",
                 "seconds", "queue_wait", "queue_depth", "error")

    def __init__(self, text, kind, source, value=None, expression=None,
                 corrections=(), seconds=0.0, queue_wait=0.0, queue_depth=0,
                 error=None):
        self.text = text
        self.kind = kind
        self.source = source
        self.value = value
        self.expression = expression
        self.corrections = list(corrections)
        self.seconds = seconds
        self.queue_wait = queue_wait
        self.queue_depth = queue_depth
        self.error = error

    def as_dict(self):
        return {"answer": self.text, "kind": self.kind, "source": self.source,
                "value": str(self.value) if self.value is not None else None,
                "expression": self.expression,
                "corrections": [c.as_dict() for c in self.corrections],
                "seconds": round(self.seconds, 2),
                "queue_wait": round(self.queue_wait, 2),
                "queue_depth": self.queue_depth, "error": self.error}

    def __repr__(self):
        return "Answer(%s/%s, %r)" % (self.kind, self.source, self.text[:60])


class Tutor(object):
    """Wires the phases together.

    `llm(messages, max_tokens)` must return the model's full text. Any exception from
    it is caught: a computational question still gets its deterministic answer, and a
    conceptual one gets an honest "couldn't answer" rather than a fabricated number.
    """

    def __init__(self, llm, hardware, log=None, queue=None, use_templates=True):
        self.llm = llm
        self.hardware = hardware
        self.log = log
        self.queue = queue or InferenceQueue(hardware.max_parallel_slots)
        self.use_templates = use_templates

    # -- model access, always through the queue --

    def _generate(self, system, user, max_tokens, on_wait=None, timeout=None,
                  context=""):
        if context:
            # Lesson context from the calling app (the video's note/transcript). It is
            # appended rather than replacing the system prompt so the accuracy rules
            # above always survive.
            system = "%s\n\nLESSON CONTENT:\n%s" % (system, context)
        with self.queue.slot(timeout=timeout, on_wait=on_wait) as waited:
            depth = self.queue.depth
            text = self.llm([{"role": "system", "content": system},
                             {"role": "user", "content": user}], max_tokens)
        return (text or "").strip(), waited, depth

    # -- paths --

    def _computational(self, question, route, on_wait, timeout, context=""):
        decimal = matheng.wants_decimal(question, route.expression)

        if route.solved:
            answer_text = (route.value.as_decimal() if decimal
                           else route.value.as_fraction())

            if self.use_templates:
                fast = templates.explain(route.expression, route.value, decimal)
                if fast:
                    # Zero inference: the number and the words both come from code, so
                    # there is nothing here that can be wrong.
                    return Answer(fast, router.COMPUTATIONAL, SOURCE_TEMPLATE,
                                  route.value, route.expression)

            user = ("Child's question: %s\nThe correct answer is: %s\nExplain how to "
                    "get %s." % (question, answer_text, answer_text))
            try:
                text, waited, depth = self._generate(WRAP_SYS, user, 140, on_wait,
                                                    timeout, context)
            except Exception as e:                # noqa: BLE001
                # The model is down or overloaded, but the answer is already known -
                # serve it plainly rather than failing the student.
                return Answer("The answer is %s." % answer_text, router.COMPUTATIONAL,
                              SOURCE_ENGINE, route.value, route.expression,
                              error="%s: %s" % (type(e).__name__, e))

            text, corrections = verify.verify(text)
            if not self._states_answer(text, route.value, decimal):
                # The model wandered off the given number. The engine is the authority,
                # so state the answer plainly and keep the explanation as support.
                text = "The answer is %s. %s" % (answer_text, text)
            return Answer(text, router.COMPUTATIONAL, SOURCE_MODEL, route.value,
                          route.expression, corrections, queue_wait=waited,
                          queue_depth=depth)

        # Computational, but the engine would not vouch for a number (an unusual
        # phrasing or a word problem outside its patterns). The model answers, and the
        # verifier still checks every equation it writes.
        try:
            text, waited, depth = self._generate(COMPUTE_SYS, question, 200, on_wait,
                                                timeout, context)
        except Exception as e:                    # noqa: BLE001
            return Answer("", router.COMPUTATIONAL, SOURCE_MODEL,
                          error="%s: %s" % (type(e).__name__, e))
        text, corrections = verify.verify(text)
        return Answer(text, router.COMPUTATIONAL, SOURCE_MODEL, corrections=corrections,
                      queue_wait=waited, queue_depth=depth)

    def _conceptual(self, question, on_wait, timeout, context=""):
        try:
            text, waited, depth = self._generate(CONCEPT_SYS, question, 220, on_wait,
                                                timeout, context)
        except Exception as e:                    # noqa: BLE001
            return Answer("", router.CONCEPTUAL, SOURCE_MODEL,
                          error="%s: %s" % (type(e).__name__, e))
        # No single correct answer to check against, but the examples inside it are
        # still arithmetic and still get checked.
        text, corrections = verify.verify(text)
        return Answer(text, router.CONCEPTUAL, SOURCE_MODEL, corrections=corrections,
                      queue_wait=waited, queue_depth=depth)

    @staticmethod
    def _states_answer(text, value, decimal):
        """Did the model actually say the number it was given?

        Bounded matching, not a substring: "The answer is 18" contains "8" but does
        not state 8, and letting that pass would skip the correction that fixes it.
        """
        for form in (value.as_decimal(), value.as_fraction(), value.as_mixed()):
            if form and re.search(r"(?<![\d.])%s(?![\d.])" % re.escape(form), text):
                return True
        return False

    # -- entry point --

    def ask(self, question, on_wait=None, timeout=None, context=""):
        """Answer one student question. Never raises; errors land on Answer.error.

        `context` is optional lesson material from the calling app - the note or
        transcript for the video the child is watching. It shapes the explanation; it
        never affects which path the question takes or what the engine computes.
        """
        started = time.time()
        route = router.classify(question)

        if route.is_computational:
            ans = self._computational(question, route, on_wait, timeout, context)
        else:
            ans = self._conceptual(question, on_wait, timeout, context)

        ans.seconds = time.time() - started

        if self.log:
            self.log.answer(self.hardware.tier, ans.kind, ans.seconds, ans.source,
                            corrections=len(ans.corrections),
                            queue_wait=ans.queue_wait, queue_depth=ans.queue_depth,
                            expression=ans.expression)
            for c in ans.corrections:
                self.log.correction(ans.kind, c.expression, c.stated, c.correct)
            if ans.error:
                self.log.warning("model call failed", detail=ans.error, kind=ans.kind)
        return ans

    def warm(self, context="", timeout=None):
        """Prime llama-server's prefix cache for the conceptual prompt plus this
        lesson's context, while the child is still watching the video.

        Worth doing precisely because it is the expensive path: the system prompt and
        the lesson text are identical for every question about that lesson, so paying
        for them once turns a cold answer into a warm one. Best effort - a failure
        here only costs speed.
        """
        try:
            self._generate(CONCEPT_SYS, "Hi", 1, timeout=timeout, context=context)
            return True
        except Exception:                         # noqa: BLE001
            return False

    def health(self):
        """For the debug/health endpoint: tier and queue depth in one object."""
        return {"hardware": self.hardware.as_dict(), "queue": self.queue.stats(),
                "templates": self.use_templates}

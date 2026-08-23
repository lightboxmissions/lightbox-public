"""Integration tests: both paths end to end, plus the concurrency behaviour.

The model is faked, deliberately including a lying model, because the whole
architecture exists to survive exactly that. The go/no-go property is:

    no wrong number ever reaches a student, whatever the model says.

Real-model checks (accuracy of conceptual explanations, and latency on genuinely weak
hardware) cannot be asserted here - those live in bench/ and need human review.
"""

import os
import tempfile
import threading
import time
import unittest

from tutor_core import router
from tutor_core.hardware import TIER_MID, TIER_WEAK, HardwareConfig
from tutor_core.logging_ import TutorLog, summarize
from tutor_core.pipeline import (SOURCE_ENGINE, SOURCE_MODEL, SOURCE_TEMPLATE, Tutor)
from tutor_core.verify import check


def hw(tier=TIER_MID):
    return HardwareConfig(tier, 4, 8, 8.0, True, model="fake.gguf")


class FakeLLM(object):
    """Records calls and returns canned text."""

    def __init__(self, reply="Sure! 2 + 2 = 4.", delay=0.0):
        self.reply = reply
        self.delay = delay
        self.calls = []
        self.lock = threading.Lock()

    def __call__(self, messages, max_tokens):
        with self.lock:
            self.calls.append(messages)
        if self.delay:
            time.sleep(self.delay)
        return self.reply if isinstance(self.reply, str) else self.reply(messages)


class TestComputationalPath(unittest.TestCase):

    def test_template_answers_with_zero_inference(self):
        llm = FakeLLM()
        t = Tutor(llm, hw())
        a = t.ask("what is 15+2")
        self.assertEqual(a.kind, router.COMPUTATIONAL)
        self.assertEqual(a.source, SOURCE_TEMPLATE)
        self.assertIn("17", a.text)
        self.assertEqual(llm.calls, [], "template path must not call the model")

    def test_model_wraps_the_precomputed_answer(self):
        llm = FakeLLM("Great question! The answer is 32 because you multiply 2 by "
                      "itself 5 times.")
        t = Tutor(llm, hw())
        a = t.ask("what is 2 to the power of 5")     # no template for exponents
        self.assertEqual(a.source, SOURCE_MODEL)
        self.assertEqual(str(a.value), "32")
        self.assertEqual(len(llm.calls), 1)
        # the pre-verified number is handed to the model, not requested from it
        self.assertIn("32", llm.calls[0][1]["content"])

    def test_lying_model_cannot_publish_a_wrong_number(self):
        llm = FakeLLM("The answer is 30 because 2 x 5 = 30.")
        t = Tutor(llm, hw())
        a = t.ask("what is 2 to the power of 5")
        self.assertEqual(check(a.text), [], "a wrong equation survived: %r" % a.text)
        self.assertIn("32", a.text)
        self.assertTrue(a.corrections)

    def test_model_that_ignores_the_given_answer_gets_overridden(self):
        """The model writes a coherent but off-topic explanation that never states the
        answer. The engine is the authority, so the answer is stated regardless."""
        llm = FakeLLM("Exponents are a way of writing repeated multiplication.")
        t = Tutor(llm, hw())
        a = t.ask("what is 2 to the power of 5")
        self.assertTrue(a.text.startswith("The answer is 32."))

    def test_model_failure_still_serves_the_computed_answer(self):
        def boom(messages, max_tokens):
            raise IOError("llama-server not running")

        t = Tutor(boom, hw())
        a = t.ask("what is 2 to the power of 5")
        self.assertEqual(a.source, SOURCE_ENGINE)
        self.assertIn("32", a.text)
        self.assertIn("llama-server not running", a.error)

    def test_unparseable_computational_question_is_still_verified(self):
        llm = FakeLLM("Split them up: 17 / 5 = 4 each with 2 left over.")
        t = Tutor(llm, hw())
        a = t.ask("if I have 17 marbles and split them between 5 friends with 2 "
                  "left over, how many does each friend get")
        self.assertEqual(a.kind, router.COMPUTATIONAL)
        self.assertEqual(check(a.text), [])
        self.assertIn("17 / 5 = 3 2/5", a.text)      # 4 was wrong, and got corrected


class TestConceptualPath(unittest.TestCase):

    def test_conceptual_always_reaches_the_model(self):
        llm = FakeLLM("Carrying moves a full group of ten into the tens column.")
        t = Tutor(llm, hw())
        a = t.ask("why do we carry the 1")
        self.assertEqual(a.kind, router.CONCEPTUAL)
        self.assertEqual(len(llm.calls), 1)
        self.assertEqual(a.corrections, [])

    def test_templates_never_apply_to_conceptual_questions(self):
        llm = FakeLLM("A fraction is a part of a whole.")
        t = Tutor(llm, hw())
        for q in ["what is a fraction", "why do we carry the 1", "explain place value"]:
            self.assertEqual(t.ask(q).source, SOURCE_MODEL, q)

    def test_wrong_example_inside_a_conceptual_answer_is_corrected(self):
        llm = FakeLLM("Dividing by a half doubles a number, like 6 / 2 = 4.")
        t = Tutor(llm, hw())
        a = t.ask("why does dividing by a fraction flip it")
        self.assertIn("6 / 2 = 3", a.text)
        self.assertEqual(len(a.corrections), 1)

    def test_model_failure_returns_an_honest_empty_answer(self):
        def boom(messages, max_tokens):
            raise IOError("timed out")

        a = Tutor(boom, hw()).ask("what is a fraction")
        self.assertEqual(a.text, "")
        self.assertIn("timed out", a.error)


class TestConcurrencyAndTiers(unittest.TestCase):

    def test_tier_1_serializes_conceptual_questions(self):
        llm = FakeLLM("A fraction is part of a whole.", delay=0.05)
        t = Tutor(llm, hw(TIER_WEAK))
        self.assertEqual(t.queue.slots, 1)
        waits = []

        def ask():
            waits.append(t.ask("what is a fraction").queue_wait)

        threads = [threading.Thread(target=ask) for _ in range(5)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        self.assertEqual(len(waits), 5)
        self.assertGreater(max(waits), 0.0, "5 students on 1 slot must queue")
        self.assertEqual(t.queue.active, 0)

    def test_five_concurrent_mixed_questions_all_answered_correctly(self):
        llm = FakeLLM("Here you go: 2 + 2 = 5.", delay=0.02)   # deliberately wrong
        t = Tutor(llm, hw())
        answers = []
        questions = ["what is 15+2", "why do we carry the 1", "what is 3 x 4",
                     "what is a fraction", "20% of 50"]

        def ask(q):
            answers.append(t.ask(q))

        threads = [threading.Thread(target=ask, args=(q,)) for q in questions]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        self.assertEqual(len(answers), 5)
        for a in answers:
            self.assertEqual(check(a.text), [],
                             "wrong number reached a student: %r" % a.text)

    def test_health_reports_tier_and_queue_depth(self):
        t = Tutor(FakeLLM(), hw())
        h = t.health()
        self.assertEqual(h["hardware"]["tier"], TIER_MID)
        self.assertEqual(h["queue"]["slots"], 3)
        self.assertEqual(h["queue"]["waiting"], 0)


class TestLogging(unittest.TestCase):

    def test_log_records_what_a_volunteer_needs(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "tutor.jsonl")
        config = hw()
        log = TutorLog(path, config)
        llm = FakeLLM("Dividing by a half doubles it, like 6 / 2 = 4.")
        t = Tutor(llm, config, log=log)
        t.ask("what is 15+2")                             # template
        t.ask("why does dividing by a fraction flip it")  # model, one correction

        stats = summarize(path)
        self.assertEqual(stats["answers"], 2)
        self.assertEqual(stats["by_kind"], {"computational": 1, "conceptual": 1})
        self.assertEqual(stats["by_source"], {"template": 1, "model": 1})
        self.assertEqual(stats["corrections"], 1)
        self.assertIn("conceptual", stats["avg_seconds"])

    def test_logging_never_makes_a_network_call(self):
        """A donated laptop in a school may sit on a hostile or metered network. The
        log must be inert."""
        import socket
        d = tempfile.mkdtemp()
        real = socket.socket

        def forbidden(*a, **k):
            raise AssertionError("logging attempted a network connection")

        socket.socket = forbidden
        try:
            log = TutorLog(os.path.join(d, "t.jsonl"), hw())
            log.answer(2, "conceptual", 1.0, "model")
            log.correction("conceptual", "6 / 2", "4", "3")
            log.warning("something")
        finally:
            socket.socket = real


if __name__ == "__main__":
    unittest.main()

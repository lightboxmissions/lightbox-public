"""Routing tests.

A misroute is not fatal - a conceptual question sent down the computational path still
gets verified, and a computational one sent to the model still gets checked. But
misrouting costs inference on hardware that has none to spare, so it is worth pinning.
"""

import unittest

from tutor_core.router import COMPUTATIONAL, CONCEPTUAL, classify

COMPUTATIONAL_QUESTIONS = [
    "what is 15+2", "whats 3 times 4", "12 x 12", "what is 3/4 as a decimal",
    "20% of 50", "sum of 12 and 30", "what is 8 squared", "square root of 144",
    "Sarah has 5 apples and gets 3 more", "24 shared equally among 6",
    "what is 45 plus 67", "half of 18", "what is 100 minus 45",
]

CONCEPTUAL_QUESTIONS = [
    "why do we carry the 1", "what is a fraction", "what is place value",
    "why does dividing by a fraction flip it", "how come 0 times anything is 0",
    "explain place value", "tell me about multiplication",
    "why is 7 + 3 = 10 and not 11", "when do we use division",
    "what does denominator mean", "how do I know which is bigger",
    "why do we need fractions",
]


class TestClassify(unittest.TestCase):

    def test_computational(self):
        for q in COMPUTATIONAL_QUESTIONS:
            self.assertEqual(classify(q).kind, COMPUTATIONAL, q)

    def test_conceptual(self):
        for q in CONCEPTUAL_QUESTIONS:
            self.assertEqual(classify(q).kind, CONCEPTUAL, q)

    def test_explanatory_cue_beats_digits(self):
        """'why is 7 + 3 = 10' contains a solvable expression but wants an
        explanation. The expression is kept for the consistency check, not answered."""
        r = classify("why is 7 + 3 = 10 and not 11")
        self.assertEqual(r.kind, CONCEPTUAL)
        self.assertFalse(r.solved)

    def test_solved_flag(self):
        r = classify("what is 15+2")
        self.assertTrue(r.solved)
        self.assertEqual(str(r.value), "17")

    def test_computational_but_unsolvable_still_routes_computational(self):
        r = classify("if I have 17 marbles and split them between 5 friends "
                     "with 2 left over, how many does each friend get")
        self.assertEqual(r.kind, COMPUTATIONAL)
        self.assertFalse(r.solved)

    def test_empty_and_junk_never_raise(self):
        for q in ["", "   ", None, "???", "asdfgh"]:
            self.assertIn(classify(q).kind, (COMPUTATIONAL, CONCEPTUAL))


if __name__ == "__main__":
    unittest.main()

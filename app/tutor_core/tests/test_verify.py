"""Verifier tests.

Two failure modes to guard, and the second is the dangerous one:

  1. missing a wrong number (a student is taught something false)
  2. "correcting" text that was already right, or mangling prose (the tutor starts
     producing nonsense on correct answers, which is worse than doing nothing)
"""

import unittest

from tutor_core.verify import check, verify


class TestCatchesWrongNumbers(unittest.TestCase):

    def test_wrong_arithmetic_in_a_conceptual_explanation(self):
        text = ("When you divide by a half you double it. For example, 6 / 2 = 4 "
                "shows this.")
        out, fixes = verify(text)
        self.assertEqual(len(fixes), 1)
        self.assertIn("6 / 2 = 3", out)

    def test_wrong_carry_example(self):
        out, fixes = verify("Carrying works because 7 + 5 = 13, so we write 3.")
        self.assertIn("7 + 5 = 12", out)
        self.assertEqual(fixes[0].stated, "13")
        self.assertEqual(fixes[0].correct, "12")

    def test_wrong_fraction_result(self):
        out, _ = verify("A half plus a quarter: 1/2 + 1/4 = 2/6 of the pizza.")
        self.assertIn("1/2 + 1/4 = 3/4", out)

    def test_wrong_decimal_result_corrected_as_a_decimal(self):
        out, fixes = verify("Divide to convert: 3/4 = 0.8 as a decimal.")
        self.assertIn("3/4 = 0.75", out)
        self.assertEqual(fixes[0].correct, "0.75")

    def test_several_errors_in_one_answer(self):
        out, fixes = verify("First 2 + 2 = 5, then 3 x 3 = 10, then 10 - 1 = 9.")
        self.assertEqual(len(fixes), 2)
        self.assertIn("2 + 2 = 4", out)
        self.assertIn("3 x 3 = 9", out)
        self.assertIn("10 - 1 = 9", out)

    def test_alternative_phrasings(self):
        for text, want in [("3 x 4 equals 11", "3 x 4 equals 12"),
                           ("3 x 4 is 11", "3 x 4 is 12"),
                           ("2 + 2 makes 5", "2 + 2 makes 4")]:
            self.assertIn(want, verify(text)[0])


class TestLeavesCorrectTextAlone(unittest.TestCase):

    def test_correct_arithmetic_untouched(self):
        for text in ["15 + 2 = 17. Nice work!",
                     "3 x 4 = 12 cookies in total.",
                     "1/2 + 1/4 = 3/4 of a pizza.",
                     "20% of 50 = 10.",
                     "Because 9 - 12 = -3, the answer goes below zero."]:
            self.assertEqual(verify(text), (text, []))

    def test_prose_numbers_untouched(self):
        """Nothing to check these against, so they must be left exactly as written."""
        for text in ["A fraction is 1 part out of 2.",
                     "There are 3 kinds of fractions you will see.",
                     "Ten times ten equals one hundred.",
                     "Place value means the 5 in 52 is worth 50.",
                     "Count 1, 2, 3 and stop.",
                     "You are 8 years old and that is great."]:
            self.assertEqual(verify(text), (text, []))

    def test_rounding_tolerated_only_where_exactness_is_impossible(self):
        # 1/3 has no exact decimal, so a rounded figure is how anyone writes it.
        self.assertEqual(check("1/3 = 0.33"), [])
        self.assertEqual(check("1/3 = 0.333"), [])
        # ...but wrong is still wrong, however few places it is written to.
        self.assertTrue(check("1/3 = 0.4"))
        # 3/4 has an exact decimal, so a rounded 0.8 is an error a child would carry.
        self.assertTrue(check("3/4 = 0.8"))
        self.assertEqual(check("3/4 = 0.75"), [])

    def test_empty_and_junk(self):
        for text in ["", None, "?!?", "= = ="]:
            self.assertEqual(check(text), [])


if __name__ == "__main__":
    unittest.main()

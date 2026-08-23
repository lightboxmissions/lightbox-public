"""Unit tests for the deterministic engine against real K-8 problems.

This is the accuracy backbone, so the bar is zero wrong answers - not "mostly right".
Cases where the engine should refuse are tested just as hard as cases where it should
compute, because a confident wrong answer is the failure mode that matters.
"""

import unittest
from fractions import Fraction

from tutor_core import matheng
from tutor_core.matheng import MathError, Value, evaluate, solve


class TestEvaluate(unittest.TestCase):

    def check(self, expr, expected):
        self.assertEqual(evaluate(expr).frac, Fraction(expected), expr)

    def test_addition(self):
        for e, v in [("1+1", 2), ("15+2", 17), ("47+38", 85), ("999+1", 1000),
                     ("0+0", 0), ("123 + 456", 579)]:
            self.check(e, v)

    def test_subtraction(self):
        for e, v in [("5-3", 2), ("52-27", 25), ("9-12", -3), ("100-1", 99),
                     ("0-0", 0)]:
            self.check(e, v)

    def test_multiplication(self):
        for e, v in [("3*4", 12), ("12 x 12", 144), ("7*8", 56), ("5*0", 0),
                     ("25 * 4", 100)]:
            self.check(e, v)

    def test_division(self):
        for e, v in [("24/6", 4), ("7/2", Fraction(7, 2)), ("100/4", 25),
                     ("1/3", Fraction(1, 3))]:
            self.check(e, v)

    def test_order_of_operations(self):
        for e, v in [("2+3*4", 14), ("(2+3)*4", 20), ("10-2-3", 5),
                     ("100/10/2", 5), ("2*3+4*5", 26), ("2**3*2", 16)]:
            self.check(e, v)

    def test_fractions_are_exact(self):
        self.check("1/3+1/3+1/3", 1)
        self.check("1/2+1/4", Fraction(3, 4))
        self.check("2/3-1/6", Fraction(1, 2))
        self.check("2/3*3/4", Fraction(1, 2))
        # Dividing by a fraction multiplies by its reciprocal: 1/2 / 1/4 = 1/2 * 4.
        self.check("(1/2)/(1/4)", 2)
        self.check("(3/4)/(1/2)", Fraction(3, 2))

    def test_decimals_are_exact(self):
        # The classic float trap: 0.1 + 0.2 must be 0.3, not 0.30000000000000004.
        self.assertEqual(evaluate("0.1+0.2").as_decimal(), "0.3")
        self.check("1.5*2", 3)
        self.check("2.5+2.5", 5)

    def test_percent(self):
        self.check("20%*50", 10)
        self.check("50%*80", 40)
        self.check("100%*7", 7)
        self.check("15%*200", 30)

    def test_mixed_numbers(self):
        self.check("1 1/2 + 2 1/4", Fraction(15, 4))
        self.check("3 1/2 * 2", 7)

    def test_exponents_and_roots(self):
        self.check("2**5", 32)
        self.check("8**2", 64)
        self.check("sqrt(144)", 12)
        self.check("sqrt(81)", 9)
        self.assertFalse(evaluate("sqrt(2)").exact)
        self.assertAlmostEqual(evaluate("sqrt(2)").as_float(), 1.41421356, places=6)

    def test_negative_and_unary(self):
        self.check("-5+3", -2)
        self.check("-(4+1)", -5)
        self.check("3*-2", -6)

    def test_implicit_multiplication(self):
        self.check("2(3+4)", 14)
        self.check("3(4)", 12)

    def test_refuses_bad_input(self):
        for bad in ["1/0", "5/(3-3)", "", "   ", "hello", "2+", "(1+2", "1+2)",
                    "2**1000", "0**-1", "sqrt(-4)", "2 3", "1 + banana"]:
            with self.assertRaises(MathError, msg=bad):
                evaluate(bad)

    def test_never_executes_input(self):
        for hostile in ["__import__('os').system('ls')", "1+1;print(2)",
                        "open('x')", "[].__class__"]:
            with self.assertRaises(MathError):
                evaluate(hostile)


class TestValueFormatting(unittest.TestCase):

    def test_forms(self):
        v = Value(Fraction(7, 2))
        self.assertEqual(v.as_fraction(), "7/2")
        self.assertEqual(v.as_mixed(), "3 1/2")
        self.assertEqual(v.as_decimal(), "3.5")
        self.assertIsNone(v.as_int())

    def test_integers_render_plainly(self):
        v = Value(12)
        self.assertEqual(v.as_fraction(), "12")
        self.assertEqual(v.as_decimal(), "12")
        self.assertEqual(v.as_mixed(), "12")
        self.assertEqual(v.as_int(), 12)

    def test_negative_mixed(self):
        self.assertEqual(Value(Fraction(-7, 2)).as_mixed(), "-3 1/2")

    def test_close_to_tolerates_rounding_not_error(self):
        third = Value(Fraction(1, 3))
        self.assertTrue(third.close_to(Fraction(1, 3)))
        self.assertFalse(third.close_to(Fraction(33, 100)))   # a rounded student answer
        self.assertFalse(third.close_to(Fraction(4, 10)))     # simply wrong


class TestSolveFromText(unittest.TestCase):

    def check(self, question, expected):
        value, _ = solve(question)
        self.assertIsNotNone(value, question)
        self.assertEqual(value.frac, Fraction(expected), question)

    def test_plain_questions(self):
        for q, v in [("what is 15+2", 17), ("what's 3 times 4", 12),
                     ("whats 100 minus 45", 55), ("how much is 8 divided by 2", 4),
                     ("calculate 25 + 25", 50), ("12 x 12", 144)]:
            self.check(q, v)

    def test_worded_operations(self):
        for q, v in [("sum of 12 and 30", 42), ("difference between 10 and 4", 6),
                     ("product of 6 and 7", 42), ("quotient of 20 and 5", 4),
                     ("half of 18", 9), ("double 7", 14), ("twice 11", 22),
                     ("5 subtracted from 12", 7), ("what is 8 squared", 64),
                     ("square root of 144", 12), ("3 more than 4", 7)]:
            self.check(q, v)

    def test_percent_phrasings(self):
        self.check("20% of 50", 10)
        self.check("20 percent of 50", 10)
        self.check("what is 25% of 80", 20)

    def test_the_article_does_not_block_the_fast_path(self):
        """Children say "what is THE sum of 12 and 30". The leftover article used to
        leave a letter in the expression, which cost a model call for an answer the
        engine already had."""
        for q, v in [("what is the sum of 12 and 30", 42),
                     ("what is the difference between 10 and 4", 6),
                     ("what is the product of 6 and 7", 42),
                     ("what is the quotient of 20 and 5", 4),
                     ("what is the square root of 144", 12)]:
            self.check(q, v)

    def test_decimal_questions_want_decimal_answers(self):
        """0.1 + 0.2 = 3/10 is correct and useless to a child working in decimals."""
        value, expr = solve("what is 0.1 + 0.2")
        self.assertTrue(matheng.wants_decimal("what is 0.1 + 0.2", expr))
        self.assertEqual(value.as_decimal(), "0.3")
        # ...and a whole-number question is unaffected
        _, expr2 = solve("what is 1 + 2")
        self.assertFalse(matheng.wants_decimal("what is 1 + 2", expr2))

    def test_conversion_requests(self):
        value, _ = solve("what is 3/4 as a decimal")
        self.assertEqual(value.as_decimal(), "0.75")
        self.assertTrue(matheng.wants_decimal("what is 3/4 as a decimal"))
        self.assertFalse(matheng.wants_decimal("what is 3/4 plus 1/4"))

    def test_simple_word_problems(self):
        for q, v in [("Sarah has 5 apples and gets 3 more", 8),
                     ("Tom had 10 cookies and ate 4", 6),
                     ("There are 3 boxes of 12 pencils", 36),
                     ("24 stickers shared equally among 6 kids", 4)]:
            self.check(q, v)

    def test_refuses_rather_than_guesses(self):
        """The engine must return nothing for anything it cannot pin down. These are
        the cases where a confident wrong number would do real damage."""
        for q in ["why do we carry the 1", "what is a fraction",
                  "what is place value", "tell me about multiplication",
                  "Sarah has some apples and gets more",
                  "is 7 bigger than 4", "what number comes after 9",
                  "what is 100 divided by 0", "how do I do long division"]:
            value, expr = solve(q)
            self.assertIsNone(value, "engine should refuse: %r (got %s)" % (q, expr))


if __name__ == "__main__":
    unittest.main()

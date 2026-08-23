"""Template tests.

The property that matters: a rendered template can never state a wrong number, because
every number in it comes from the engine's Value. So each test checks the answer is
present AND that running the output back through the verifier finds nothing to fix.
"""

import unittest

from tutor_core import verify
from tutor_core.router import classify
from tutor_core.matheng import wants_decimal
from tutor_core.templates import explain


def render(question):
    r = classify(question)
    return explain(r.expression, r.value, wants_decimal(question)), r


class TestTemplates(unittest.TestCase):

    def assert_sound(self, question, must_contain):
        text, route = render(question)
        self.assertIsNotNone(text, "no template matched: %r" % question)
        self.assertIn(must_contain, text, question)
        corrected, fixes = verify.verify(text)
        self.assertEqual(fixes, [], "template stated a wrong number: %r -> %r"
                         % (question, text))

    def test_addition(self):
        self.assert_sound("what is 15+2", "17")
        self.assert_sound("what is 47+38", "85")

    def test_carry_hint_only_when_it_carries(self):
        with_carry, _ = render("what is 47+38")
        without, _ = render("what is 41+12")
        self.assertIn("carry", with_carry)
        self.assertNotIn("carry", without)

    def test_subtraction(self):
        self.assert_sound("what is 8-3", "5")
        self.assert_sound("what is 52-27", "25")

    def test_borrow_hint_only_when_it_borrows(self):
        with_borrow, _ = render("what is 52-27")
        without, _ = render("what is 58-27")
        self.assertIn("borrow", with_borrow)
        self.assertNotIn("borrow", without)

    def test_negative_result_explained_not_hidden(self):
        text, _ = render("what is 9-12")
        self.assertIn("-3", text)
        self.assertIn("below zero", text)

    def test_multiplication(self):
        self.assert_sound("what is 3 x 4", "12")

    def test_multiplication_by_zero_is_special_cased(self):
        text, _ = render("what is 5 times 0")
        self.assertIn("0", text)
        self.assertIn("nothing", text)

    def test_division_exact_and_with_remainder(self):
        self.assert_sound("what is 24 divided by 6", "4")
        text, _ = render("what is 7 divided by 2")
        self.assertIn("3 1/2", text)

    def test_division_by_zero_has_no_template(self):
        """Dividing by zero is a concept question, not a computation - it must fall
        through to the model rather than get a templated non-answer."""
        from tutor_core.matheng import evaluate, MathError
        with self.assertRaises(MathError):
            evaluate("5/0")
        self.assertIsNone(explain("5/0", None))

    def test_fraction_same_denominator(self):
        text, _ = render("what is 1/4 + 1/4")
        self.assertIn("1/2", text)
        self.assertIn("same", text)

    def test_fraction_different_denominator_names_the_common_one(self):
        text, _ = render("what is 1/2 + 1/3")
        self.assertIn("5/6", text)
        self.assertIn("6 on the bottom", text)

    def test_percent(self):
        self.assert_sound("20% of 50", "10")

    def test_decimal_conversion_uses_conversion_wording(self):
        text, _ = render("what is 3/4 as a decimal")
        self.assertIn("0.75", text)
        self.assertNotIn("groups", text)

    def test_worded_phrasings_reach_the_fast_path(self):
        """These arrive as "(12)+(30)" from the phrase rewriter. Missing the template
        over redundant parentheses cost a model call each - 5 to 16 seconds on Tier 1
        hardware, for an answer the engine already had."""
        for q, want in [("what is the sum of 12 and 30", "42"),
                        ("what is the difference between 10 and 4", "6"),
                        ("what is the product of 6 and 7", "42"),
                        ("what is the quotient of 20 and 5", "4"),
                        ("what is half of 18", "9"),
                        ("what is double 7", "14")]:
            self.assert_sound(q, want)

    def test_subtraction_teaches_one_method_at_a_time(self):
        """Small numbers get counting back; column numbers get column talk. Saying
        "count back 4" and "borrow a ten" in one breath describes two methods."""
        small, _ = render("Tom had 10 cookies and ate 4")
        self.assertIn("count back", small)
        self.assertNotIn("borrow", small)
        big, _ = render("what is 52 - 27")
        self.assertNotIn("count back", big)
        self.assertIn("borrow", big)

    def test_no_template_falls_through(self):
        """Anything without a template must return None so the caller uses the model.
        Returning a vague string here would silently replace real teaching."""
        self.assertIsNone(render("what is 2 to the power of 5")[0])
        self.assertIsNone(explain(None, None))
        self.assertIsNone(explain("1+1", None))


if __name__ == "__main__":
    unittest.main()

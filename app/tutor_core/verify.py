"""Verify-and-correct pass over model output.

Applies to both paths:

  * computational - the explanation wraps a pre-computed number, but the model can
    still contradict itself while restating the working.
  * conceptual - the question had no computable answer, yet the explanation is full of
    supporting examples. "Dividing by a half doubles it, like 6 / 2 = 4" must still be
    caught, even though nothing about the original question was computational.

Only equations are checked - a span with an operator and a stated result. Prose numbers
("there are 3 kinds of fractions") are left alone, because there is nothing to check
them against and rewriting them would corrupt correct text.

Corrections replace only the stated result inside the matched span. Nothing else in the
model's wording is touched.
"""

import re

from . import matheng

__all__ = ["Correction", "check", "apply_corrections", "verify"]

# "3 x 4 = 12", "3 x 4 is 12", "3 x 4 equals 12". The left side must contain an
# operator, which is what keeps ordinary sentences ("a fraction is 1 part of 2") out.
_EQUATION = re.compile(r"""
    (?P<lhs>
        (?:\d+(?:\.\d+)?|\d+\s*/\s*\d+)
        (?:\s*(?:[-+*/^]|x|×|÷|plus|minus|times|divided\s+by|multiplied\s+by)\s*
           (?:\d+(?:\.\d+)?|\d+\s*/\s*\d+))+
    )
    \s*(?:=|equals|is\s+equal\s+to|is|makes|gives)\s*
    (?P<rhs>
        -?\d+\s+\d+\s*/\s*\d+          # mixed number first: "3 1/2" is one answer,
      | -?\d+(?:\.\d+)?(?:\s*/\s*\d+)? # not the number 3 followed by junk
    )
    (?![\d/])
""", re.X | re.I)


class Correction(object):
    """One numeric claim the model got wrong."""

    __slots__ = ("span", "expression", "stated", "correct")

    def __init__(self, span, expression, stated, correct):
        self.span = span
        self.expression = expression
        self.stated = stated
        self.correct = correct

    def as_dict(self):
        return {"expression": self.expression, "stated": self.stated,
                "correct": self.correct}

    def __repr__(self):
        return "Correction(%s = %s, model said %s)" % (
            self.expression, self.correct, self.stated)


def _stated_value(text):
    try:
        return matheng.evaluate(text)
    except matheng.MathError:
        return None


def _terminates(frac):
    """True if the fraction has an exact decimal form (denominator is only 2s and 5s)."""
    d = frac.denominator
    for p in (2, 5):
        while d % p == 0:
            d //= p
    return d == 1


def _acceptable(truth, rhs_text, stated):
    """Is the model's stated figure right?

    Exact matches pass. Rounding is tolerated only where exactness is impossible:
    "1/3 = 0.33" is how anyone writes it, but "3/4 = 0.8" is a rounded answer to a
    question that has an exact one, and a child taught that will carry the error.
    """
    if truth.close_to(stated):
        return True
    if "." not in rhs_text or _terminates(truth.frac):
        return False
    places = len(rhs_text.split(".")[1])
    return round(truth.as_float(), places) == round(stated.as_float(), places)


def check(text):
    """Find every wrong equation in `text`. Returns a list of Correction."""
    out = []
    if not text:
        return out
    for m in _EQUATION.finditer(text):
        lhs, rhs = m.group("lhs"), m.group("rhs")
        expr = matheng.to_expression(lhs)
        if not expr:
            continue
        try:
            truth = matheng.evaluate(expr)
        except matheng.MathError:
            continue                      # unparseable or undefined: not our call
        stated = _stated_value(rhs)
        if stated is None or _acceptable(truth, rhs, stated):
            continue
        # Render the correction the way the model rendered its answer, so a decimal
        # claim is corrected with a decimal and a fraction with a fraction. Improper
        # fractions become mixed numbers - "17 / 5 = 17/5" restates the question, while
        # "17 / 5 = 3 2/5" is the answer a K-8 answer key gives.
        if "." in rhs:
            correct = truth.as_decimal()
        elif abs(truth.frac) > 1 and not truth.is_integer():
            correct = truth.as_mixed()
        else:
            correct = truth.as_fraction()
        out.append(Correction(m.span("rhs"), lhs.strip(), rhs.strip(), correct))
    return out


def apply_corrections(text, corrections):
    """Rewrite only the wrong results, right to left so earlier spans stay valid."""
    for c in sorted(corrections, key=lambda c: c.span[0], reverse=True):
        start, end = c.span
        text = text[:start] + c.correct + text[end:]
    return text


def verify(text):
    """Convenience wrapper: returns (corrected_text, corrections)."""
    corrections = check(text)
    if not corrections:
        return text, []
    return apply_corrections(text, corrections), corrections

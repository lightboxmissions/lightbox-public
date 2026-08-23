"""Templated explanations for common computational patterns (Phase 2b fast path).

Skips LLM inference entirely for the questions students ask most, which frees the
model for conceptual questions that cannot be templated. Used on every tier, not just
weak hardware - a correct instant answer beats a correct slow one.

Never applies to conceptual questions. There is no template for "why do we carry the
1"; that is real explanation work and always goes to the model.

Every number in the output comes from the deterministic engine's Value, so a rendered
template cannot state a wrong result. The only failure mode is not matching, which
falls through to the LLM.
"""

import re

from .matheng import Value

__all__ = ["explain"]

_INT = r"-?\d+"
_FRACT = r"-?\d+\s*/\s*\d+"
_NUM = r"-?\d+(?:\.\d+)?"

_ADD = re.compile(r"^\s*(%s)\s*\+\s*(%s)\s*$" % (_INT, _INT))
_SUB = re.compile(r"^\s*(%s)\s*-\s*(%s)\s*$" % (_INT, _INT))
_MUL = re.compile(r"^\s*(%s)\s*(?:\*|x)\s*(%s)\s*$" % (_INT, _INT), re.I)
_DIV = re.compile(r"^\s*(%s)\s*/\s*(%s)\s*$" % (_INT, _INT))
_FRAC_ADD = re.compile(r"^\s*(%s)\s*([+-])\s*(%s)\s*$" % (_FRACT, _FRACT))
_PERCENT = re.compile(r"^\s*(%s)\s*%%\s*\*\s*(%s)\s*$" % (_NUM, _NUM))


_REDUNDANT_PARENS = re.compile(r"\((\s*-?\d+(?:\.\d+)?\s*)\)")


def _unwrap(expr):
    """Drop parentheses that only wrap a single number.

    The worded phrasings produce "(12)+(30)" so the operands stay grouped during
    rewriting. Without this, "the sum of 12 and 30" would miss its template and cost a
    model call for an answer the engine already has.
    """
    return _REDUNDANT_PARENS.sub(r"\1", expr)


def _n(s):
    """Render an operand the way it was written, without a trailing '.0'."""
    s = re.sub(r"\s+", "", str(s))
    return s[:-2] if s.endswith(".0") else s


def _place_value_hint(a, b):
    """Only mention carrying when the ones column actually carries - telling a child
    to carry when there is nothing to carry teaches the wrong rule."""
    if a % 10 + b % 10 >= 10 and (a >= 10 or b >= 10):
        return (" The ones add up to more than 9, so we carry 1 ten over to the "
                "tens column.")
    return ""


def _borrow_hint(a, b):
    if a % 10 < b % 10 and a >= 10:
        return (" There aren't enough ones to take %d away, so we borrow 1 ten from "
                "the tens column and turn it into 10 ones." % (b % 10))
    return ""


def explain(expression, value, decimal=False):
    """Render an explanation for a computed answer, or None if no template fits.

    `value` must be the engine's Value for `expression`. None means "no fast path" -
    the caller sends the question to the model instead.
    """
    if not isinstance(value, Value) or not expression:
        return None
    expr = _unwrap(expression.replace("**", "^").strip())
    answer = value.as_decimal() if decimal else value.as_fraction()

    if decimal:
        m = _DIV.match(expr)
        if m and int(m.group(2)) != 0:
            a, b = int(m.group(1)), int(m.group(2))
            return ("%d/%d = %s. A fraction is a division, so divide the top number by "
                    "the bottom one: %d divided by %d is %s."
                    % (a, b, answer, a, b, answer))

    m = _ADD.match(expr)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if b < 10 and a < 20:
            return ("%d + %d = %s. Start at %d and count on %d more.%s"
                    % (a, b, answer, a, b, _place_value_hint(a, b)))
        return ("%d + %d = %s. Add the ones column first, then the tens column.%s"
                % (a, b, answer, _place_value_hint(a, b)))

    m = _SUB.match(expr)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if value.frac < 0:
            return ("%d - %d = %s. You can't take %d away from only %d, so the answer "
                    "goes below zero." % (a, b, answer, b, a))
        if b < 10 and a < 20:
            # Small numbers: counting back is the method. Mentioning borrowing here
            # too would describe two different methods in one breath.
            return "%d - %d = %s. Start at %d and count back %d." % (a, b, answer, a, b)
        return ("%d - %d = %s. Subtract the ones column first, then the tens column.%s"
                % (a, b, answer, _borrow_hint(a, b)))

    m = _MUL.match(expr)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if 0 in (a, b):
            return ("%d x %d = 0. Any number of groups of nothing - or nothing at all "
                    "of something - is always 0." % (a, b))
        return ("%d x %d = %s. That's %d groups with %d in each group, or %d added "
                "together %d times." % (a, b, answer, a, b, b, a))

    m = _DIV.match(expr)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if b == 0:
            return None                       # a real concept question, not a template
        if value.is_integer():
            return ("%d / %d = %s. If you share %d things equally between %d groups, "
                    "each group gets %s." % (a, b, answer, a, b, answer))
        whole = a // b
        rest = a - whole * b
        return ("%d / %d = %s. Each of the %d groups gets %d whole ones, and %d is "
                "left over to share, which makes %s."
                % (a, b, value.as_mixed(), b, whole, rest, value.as_mixed()))

    m = _FRAC_ADD.match(expr)
    if m:
        left, op, right = m.group(1).replace(" ", ""), m.group(2), m.group(3).replace(" ", "")
        d1 = int(left.split("/")[1])
        d2 = int(right.split("/")[1])
        word = "add" if op == "+" else "subtract"
        if d1 == d2:
            return ("%s %s %s = %s. The bottom numbers are the same, so we just %s the "
                    "top numbers and keep the bottom number %d."
                    % (left, op, right, answer, word, d1))
        common = d1 * d2 // _gcd(d1, d2)
        return ("%s %s %s = %s. The bottom numbers are different, so first rewrite both "
                "fractions with %d on the bottom, then %s the top numbers."
                % (left, op, right, answer, common, word))

    m = _PERCENT.match(expr)
    if m:
        pct, whole = _n(m.group(1)), _n(m.group(2))
        return ("%s%% of %s = %s. Percent means 'out of 100', so %s%% is %s/100, and "
                "we multiply that by %s." % (pct, whole, answer, pct, pct, whole))

    return None


def _gcd(a, b):
    while b:
        a, b = b, a % b
    return a

"""Deterministic math engine for K-8 arithmetic.

The LLM never has final authority over a number. Every number that reaches a student
is either computed here or cross-checked against a computation from here.

Exact by construction: values are fractions.Fraction, so 1/3 + 1/3 + 1/3 is exactly 1
and 0.1 + 0.2 is exactly 0.3. Irrational results (non-perfect roots) fall back to a
rounded Fraction and mark themselves inexact.

No eval() anywhere - parsing is recursive descent over a fixed grammar, so a malformed
or hostile question can only raise MathError, never execute anything.

The engine says "I don't know" (returns None) rather than guessing. A wrong answer
carrying the engine's authority is far worse than a question falling through to the
LLM, so every extraction path here is deliberately narrow.

Pure standard library. No dependency on model tier - this is the accuracy backbone for
the whole system, not a weak-hardware fallback.
"""

import math
import re
from fractions import Fraction

__all__ = ["MathError", "Value", "evaluate", "solve", "to_expression"]


class MathError(Exception):
    """Raised for anything the engine cannot evaluate exactly and safely."""


# ---------- values ----------

class Value:
    """A computed number, plus whether it is exact.

    Kept as a Fraction so repeated arithmetic never drifts. `exact` is False only when
    an irrational intermediate (a non-perfect root) forced a rounded value.
    """

    __slots__ = ("frac", "exact")

    def __init__(self, frac, exact=True):
        self.frac = Fraction(frac)
        self.exact = exact

    # -- formatting --

    def is_integer(self):
        return self.frac.denominator == 1

    def as_int(self):
        return int(self.frac) if self.is_integer() else None

    def as_float(self):
        return float(self.frac)

    def as_decimal(self, places=6):
        """Decimal string, trailing zeros stripped. 3/4 -> '0.75', 1/3 -> '0.333333'."""
        if self.is_integer():
            return str(int(self.frac))
        s = ("%.*f" % (places, float(self.frac))).rstrip("0").rstrip(".")
        return s or "0"

    def as_fraction(self):
        """Fraction string in lowest terms. Integers render as integers."""
        if self.is_integer():
            return str(int(self.frac))
        return "%d/%d" % (self.frac.numerator, self.frac.denominator)

    def as_mixed(self):
        """Mixed number for improper fractions: 7/2 -> '3 1/2'. Proper stay as-is."""
        if self.is_integer() or abs(self.frac) < 1:
            return self.as_fraction()
        sign = "-" if self.frac < 0 else ""
        n, d = abs(self.frac.numerator), self.frac.denominator
        return "%s%d %d/%d" % (sign, n // d, n % d, d)

    def __str__(self):
        # Default rendering: exact fraction form, which is what a K-8 answer key uses.
        # Callers that specifically want a decimal ask for one.
        return self.as_fraction() if self.exact else self.as_decimal()

    def __repr__(self):
        return "Value(%s, exact=%s)" % (self.as_fraction(), self.exact)

    def __eq__(self, other):
        if isinstance(other, Value):
            return self.frac == other.frac
        try:
            return self.frac == Fraction(other)
        except (TypeError, ValueError):
            return NotImplemented

    def __hash__(self):
        return hash(self.frac)

    def close_to(self, other, tol=Fraction(1, 10 ** 6)):
        """Numeric comparison with tolerance, for checking a rounded LLM figure.

        A student writing 0.33 for 1/3 is right; an LLM writing 0.4 is not.
        """
        o = other.frac if isinstance(other, Value) else Fraction(other)
        return abs(self.frac - o) <= tol


# ---------- tokenizer ----------

# Mixed numbers must be matched before bare integers, or "1 1/2" tokenizes as 1, 1/2.
_TOKEN = re.compile(r"""
      (?P<mixed>\d+\s+\d+\s*/\s*\d+)
    | (?P<dec>\d+\.\d+|\.\d+)
    | (?P<int>\d+)
    | (?P<name>[a-z]+)
    | (?P<op>\*\*|[-+*/^()%])
    | (?P<space>\s+)
""", re.X)

# Unicode and keyboard spellings of the four operations, normalized before tokenizing.
_SYMBOL_FIXUPS = [
    ("×", "*"), ("÷", "/"), ("−", "-"),
    ("–", "-"), ("—", "-"), (",", ""),
]


def _tokenize(s):
    for a, b in _SYMBOL_FIXUPS:
        s = s.replace(a, b)
    s = s.lower()
    out, pos = [], 0
    while pos < len(s):
        m = _TOKEN.match(s, pos)
        if not m:
            raise MathError("unexpected character %r" % s[pos])
        pos = m.end()
        kind = m.lastgroup
        text = m.group()
        if kind == "space":
            continue
        if kind == "mixed":
            whole, _, frac = text.partition(" ")
            num, _, den = frac.partition("/")
            if int(den) == 0:
                raise MathError("division by zero")
            out.append(("num", Fraction(int(whole)) + Fraction(int(num), int(den))))
        elif kind == "dec":
            out.append(("num", Fraction(text)))
        elif kind == "int":
            out.append(("num", Fraction(int(text))))
        elif kind == "name":
            # 'x' between numbers is multiplication ("3 x 4"); there are no variables in
            # this scope, so a bare letter anywhere else is a parse error, not a symbol.
            if text == "x":
                out.append(("op", "*"))
            elif text in _FUNCTIONS:
                out.append(("name", text))
            else:
                raise MathError("unknown word %r in expression" % text)
        else:
            out.append(("op", "**" if text in ("^", "**") else text))
    out.append(("end", None))
    return out


# ---------- parser ----------
#
#   expr   := term (('+' | '-') term)*
#   term   := power (('*' | '/') power)*
#   power  := unary ('**' power)?          right-associative
#   unary  := '-' unary | postfix
#   postfix:= atom '%'*                    trailing % means "per hundred"
#   atom   := NUM | NAME '(' expr ')' | '(' expr ')'
#
# Implicit multiplication is accepted between an atom and a following '(' or number,
# so "2(3+4)" and "3(4)" work the way a child would write them.

def _sqrt(v):
    r = math.isqrt(v.frac.numerator) if v.frac.denominator == 1 and v.frac >= 0 else None
    if v.frac < 0:
        raise MathError("square root of a negative number")
    if r is not None and r * r == v.frac.numerator:
        return Value(r, v.exact)
    # Irrational: keep 12 significant digits and mark the result inexact so callers
    # know not to present it as an exact fraction.
    return Value(Fraction(round(math.sqrt(float(v.frac)), 12)).limit_denominator(10 ** 9), False)


_FUNCTIONS = {"sqrt": _sqrt}


class _Parser:
    def __init__(self, tokens):
        self.toks = tokens
        self.i = 0

    def peek(self):
        return self.toks[self.i]

    def take(self):
        t = self.toks[self.i]
        self.i += 1
        return t

    def expect_op(self, op):
        kind, val = self.take()
        if kind != "op" or val != op:
            raise MathError("expected %r" % op)

    def parse(self):
        v = self.expr()
        if self.peek()[0] != "end":
            raise MathError("trailing input")
        return v

    def expr(self):
        v = self.term()
        while self.peek() == ("op", "+") or self.peek() == ("op", "-"):
            op = self.take()[1]
            r = self.term()
            v = Value(v.frac + r.frac if op == "+" else v.frac - r.frac,
                      v.exact and r.exact)
        return v

    def term(self):
        v = self.power()
        while True:
            t = self.peek()
            if t == ("op", "*") or t == ("op", "/"):
                op = self.take()[1]
                r = self.power()
                if op == "/":
                    if r.frac == 0:
                        raise MathError("division by zero")
                    v = Value(v.frac / r.frac, v.exact and r.exact)
                else:
                    v = Value(v.frac * r.frac, v.exact and r.exact)
            elif t == ("op", "("):
                # Implicit multiplication before a bracket only: 2(3+4), 3(4).
                # Two bare numbers side by side ("2 3") stays an error - it is far
                # more likely a typo than a child's way of writing 2 x 3, and mixed
                # numbers like "1 1/2" are already one token by then.
                r = self.power()
                v = Value(v.frac * r.frac, v.exact and r.exact)
            else:
                return v

    def power(self):
        v = self.unary()
        if self.peek() == ("op", "**"):
            self.take()
            e = self.power()
            if e.frac.denominator != 1:
                raise MathError("fractional exponent out of scope")
            n = int(e.frac)
            if abs(n) > 64:
                raise MathError("exponent too large")
            if v.frac == 0 and n < 0:
                raise MathError("division by zero")
            return Value(v.frac ** n, v.exact and e.exact)
        return v

    def unary(self):
        if self.peek() == ("op", "-"):
            self.take()
            v = self.unary()
            return Value(-v.frac, v.exact)
        if self.peek() == ("op", "+"):
            self.take()
            return self.unary()
        return self.postfix()

    def postfix(self):
        v = self.atom()
        while self.peek() == ("op", "%"):
            self.take()
            v = Value(v.frac / 100, v.exact)
        return v

    def atom(self):
        kind, val = self.take()
        if kind == "num":
            return Value(val)
        if kind == "name":
            self.expect_op("(")
            arg = self.expr()
            self.expect_op(")")
            return _FUNCTIONS[val](arg)
        if kind == "op" and val == "(":
            v = self.expr()
            self.expect_op(")")
            return v
        raise MathError("unexpected token %r" % (val,))


def evaluate(expression):
    """Evaluate an arithmetic expression string exactly. Raises MathError on anything
    it cannot evaluate. Never executes the input."""
    if not isinstance(expression, str) or not expression.strip():
        raise MathError("empty expression")
    if len(expression) > 200:
        raise MathError("expression too long")
    return _Parser(_tokenize(expression)).parse()


# ---------- natural language front end ----------

# Worded operators. Longest phrases first so "multiplied by" wins over "by".
_WORD_OPS = [
    (r"\bdivided\s+by\b", "/"), (r"\bmultiplied\s+by\b", "*"),
    (r"\btimes\b", "*"), (r"\bplus\b", "+"), (r"\bminus\b", "-"),
    (r"\bsubtract(?:ed)?\s+from\b", "<subfrom>"),  # reversed operands, handled below
    (r"\bover\b", "/"), (r"\bto\s+the\s+power\s+of\b", "^"),
    (r"\bsquared\b", "^2"), (r"\bcubed\b", "^3"),
    (r"\badded\s+to\b", "+"), (r"\bmore\s+than\b", "+"),
]

# "sum of A and B" style phrases: (pattern, template).
_PHRASES = [
    (r"\bsum\s+of\s+(?P<a>[^,]+?)\s+and\s+(?P<b>[^,?.]+)", "({a})+({b})"),
    (r"\bdifference\s+(?:between|of)\s+(?P<a>[^,]+?)\s+and\s+(?P<b>[^,?.]+)", "({a})-({b})"),
    (r"\bproduct\s+of\s+(?P<a>[^,]+?)\s+and\s+(?P<b>[^,?.]+)", "({a})*({b})"),
    (r"\bquotient\s+of\s+(?P<a>[^,]+?)\s+and\s+(?P<b>[^,?.]+)", "({a})/({b})"),
    (r"\bsquare\s+root\s+of\s+(?P<a>[^,?.]+)", "sqrt({a})"),
    (r"\bhalf\s+of\s+(?P<a>[^,?.]+)", "({a})/2"),
    (r"\b(?:double|twice)\s+(?P<a>[^,?.]+)", "2*({a})"),
]

# Word problems. Deliberately narrow: each pattern must pin down both numbers AND the
# operation from an explicit cue verb. Anything vaguer returns None and goes to the LLM
# rather than producing a confidently wrong "verified" answer.
_WORD_PROBLEMS = [
    (r"(\d+)[^.?!\d]{0,60}?\b(?:more|gets?|got|buys?|bought|finds?|found|adds?|receives?)\b[^.?!\d]{0,30}?(\d+)", "{0}+{1}"),
    (r"(\d+)[^.?!\d]{0,60}?\b(?:gives?\s+away|gave\s+away|loses?|lost|eats?|ate|sells?|sold|spends?|spent|takes?\s+away|removes?)\b[^.?!\d]{0,30}?(\d+)", "{0}-{1}"),
    (r"(\d+)\s+(?:groups?|boxes|bags|rows|packs?|sets?|piles?)\s+of\s+(\d+)", "{0}*{1}"),
    (r"(\d+)[^.?!\d]{0,40}?\b(?:shared|split|divided|separated)\b[^.?!\d]{0,40}?(\d+)", "{0}/{1}"),
]

_STRIP_PREFIX = re.compile(
    r"^\s*(?:hey|hi|ok|okay|so|um|please)?[,\s]*"
    r"(?:can\s+you\s+)?(?:tell\s+me\s+)?(?:what(?:'s|s|\s+is|\s+does)?|how\s+much\s+is|"
    r"calculate|compute|solve|work\s+out|find|evaluate)\s+", re.I)

# "3/4 as a decimal" asks for a different rendering of the same value, not a different
# computation - drop the phrase so the expression parses, and let wants_decimal()
# decide how to print the result.
_STRIP_SUFFIX = re.compile(
    r"\s+(?:written\s+)?(?:as|in|into)\s+(?:an?\s+)?"
    r"(?:decimal|decimals|fraction|percent|percentage|mixed\s+number)s?\s*$", re.I)

# 'x' is allowed here because the tokenizer only accepts it between numbers, where it
# can only mean multiplication (there are no variables in K-8 arithmetic scope).
_EXPR_CHARS = re.compile(r"^[\dxX\s.+\-*/^()%]+$")
_HAS_OP = re.compile(r"[+\-*/^]|\bx\b|\bsqrt\b", re.I)


def _clean(text):
    t = text.strip().rstrip("?!.")
    t = _STRIP_PREFIX.sub("", t, count=1)
    # Children say "what is THE sum of 12 and 30". The leftover article is a letter in
    # what has to end up an arithmetic expression, so it must go.
    t = re.sub(r"^the\s+", "", t, count=1, flags=re.I)
    t = _STRIP_SUFFIX.sub("", t, count=1)
    return t.strip()


def to_expression(text):
    """Turn a computational question into an arithmetic expression string, or None.

    None means "not confidently computable" - the caller must not fabricate a number.
    """
    if not isinstance(text, str) or not text.strip():
        return None
    t = _clean(text).lower()
    for a, b in _SYMBOL_FIXUPS:
        t = t.replace(a, b)

    # "A subtracted from B" reverses operand order, so resolve it before the generic
    # word-operator pass turns the sentence into infix.
    m = re.search(r"(?P<a>[\d\s./+*()-]+?)\s+subtracted\s+from\s+(?P<b>[\d\s./+*()-]+)", t)
    if m:
        t = "(%s)-(%s)" % (m.group("b"), m.group("a"))

    for pat, tmpl in _PHRASES:
        m = re.search(pat, t)
        if m:
            t = t[:m.start()] + tmpl.format(**m.groupdict()) + t[m.end():]

    t = re.sub(r"(\d)\s*percent\b", r"\1%", t)

    # "20% of 50" / "1/2 of 8" -> multiplication. Only when a number precedes "of",
    # so "half of" (already rewritten) and prose "of" don't get mangled.
    t = re.sub(r"(\d\s*%?)\s+of\s+", r"\1*", t)

    for pat, sym in _WORD_OPS:
        t = re.sub(pat, sym, t)

    t = t.replace("^", "**")
    candidate = t.strip()
    if _EXPR_CHARS.match(candidate.replace("**", "^")) and _HAS_OP.search(candidate):
        return candidate
    if candidate.startswith("sqrt(") and candidate.endswith(")"):
        return candidate

    # Fall back to word-problem patterns only if the sentence is not already an
    # expression - these are the guessiest rules in the engine, so they are fenced in.
    #
    # A third number means a distractor or a multi-step problem ("17 marbles between 5
    # friends with 2 left over" is not 17/5), and the patterns cannot tell which number
    # belongs to which step. Refusing sends it to the model, which is right; answering
    # would hand a wrong number the engine's authority, which is the one thing this
    # module must never do.
    if len(re.findall(r"\d+(?:\.\d+)?", t)) != 2:
        return None
    for pat, tmpl in _WORD_PROBLEMS:
        m = re.search(pat, t)
        if m:
            return tmpl.format(*m.groups())
    return None


def wants_decimal(text, expression=None):
    """Should the answer be shown as a decimal?

    Either the child asked for one, or they wrote the question in decimals - answering
    "0.1 + 0.2" with "3/10" is correct and useless.
    """
    if re.search(r"\bas\s+a\s+decimal\b|\bin\s+decimal(?:s)?\b", text or "", re.I):
        return True
    return bool(expression and re.search(r"\d\.\d", expression))


def wants_percent(text):
    return bool(re.search(r"\bas\s+a\s+percent(?:age)?\b", text or "", re.I))


def solve(text):
    """Compute a student question. Returns (Value, expression) or (None, None).

    (None, None) is a real answer meaning "the engine will not vouch for a number
    here" - the caller routes to the LLM instead of inventing one.
    """
    expr = to_expression(text)
    if not expr:
        return None, None
    try:
        return evaluate(expr), expr
    except MathError:
        return None, None

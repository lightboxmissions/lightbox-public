"""Question routing: computational vs conceptual.

Runs before any hardware-tier logic, because the route decides how much real LLM work
the machine is actually going to face. A computational question can often be answered
with zero inference; a conceptual one never can.

    COMPUTATIONAL - one correct numeric answer ("what's 15+2", "3/4 as a decimal").
                    The deterministic engine computes the number first; language wraps
                    a pre-verified result.
    CONCEPTUAL    - explanation, no single computable answer ("why do we carry the 1").
                    Real generation, reviewed afterwards for numeric consistency.

Rule-based on purpose. A regex classifier is inspectable, instant, and costs no
inference on a 2012 dual-core; it is also easy to replace later behind this same
`classify()` signature.
"""

import re

from . import matheng

COMPUTATIONAL = "computational"
CONCEPTUAL = "conceptual"

__all__ = ["COMPUTATIONAL", "CONCEPTUAL", "Route", "classify"]

# Words that signal the child wants to understand something, not to be handed a number.
# These win over the presence of digits: "why is 7 + 3 = 10 and not 11" is conceptual.
_CONCEPTUAL_CUES = re.compile(
    r"\b(?:why|how\s+come|what\s+does\s+it\s+mean|what\s+is\s+meant|explain|"
    r"tell\s+me\s+about|what\s+are\s+.*\s+for|when\s+do\s+(?:i|we|you)|"
    r"how\s+do\s+(?:i|we|you)\s+know|difference\s+between\s+a\b|reason)\b", re.I)

# "what is a fraction" / "what is place value" - a definition request. The article or
# the absence of any digit is what separates it from "what is 3 + 4".
_DEFINITION = re.compile(
    r"^\s*(?:what|whats|what's)\s+(?:is|are)\s+(?:a|an|the)?\s*[a-z][a-z\s\-]*\??\s*$", re.I)

_HAS_DIGIT = re.compile(r"\d")
_HAS_OPERATOR = re.compile(r"[+\-*/^=×÷]|\b(?:plus|minus|times|divided\s+by|multiplied\s+by|"
                           r"add|subtract|multiply|divide|sum|product|quotient|difference|"
                           r"percent|squared|cubed|square\s+root|half\s+of|double|twice)\b", re.I)

# Word problems carry no operator symbol at all - the arithmetic is in the story. With
# numbers present, these phrases mean a specific quantity is being asked for.
_WORD_PROBLEM_CUES = re.compile(
    r"\b(?:how\s+many|how\s+much|altogether|in\s+total|left\s+over|each|apiece|"
    r"share[ds]?|shared|split|per)\b", re.I)


class Route(object):
    """Routing decision. `expression` and `value` are filled in only when the
    deterministic engine could actually compute the answer."""

    __slots__ = ("kind", "expression", "value", "reason")

    def __init__(self, kind, expression=None, value=None, reason=""):
        self.kind = kind
        self.expression = expression
        self.value = value
        self.reason = reason

    @property
    def is_computational(self):
        return self.kind == COMPUTATIONAL

    @property
    def solved(self):
        """True when a verified number exists. A computational question the engine
        could not parse is still computational, but has no trusted answer yet."""
        return self.value is not None

    def __repr__(self):
        return "Route(%s, expr=%r, value=%s, reason=%r)" % (
            self.kind, self.expression, self.value, self.reason)


def classify(text):
    """Route a student question. Always returns a Route; never raises."""
    q = (text or "").strip()
    if not q:
        return Route(CONCEPTUAL, reason="empty question")

    # The engine's own opinion is the strongest signal available: if it can turn the
    # sentence into an expression and evaluate it, there is a single correct number.
    value, expression = matheng.solve(q)

    if _CONCEPTUAL_CUES.search(q):
        # Explanation requested. Any expression found is an example inside the
        # question, not the thing being asked for - keep it for the consistency check
        # but do not answer with it.
        return Route(CONCEPTUAL, expression=expression, reason="explanatory cue word")

    if value is not None:
        return Route(COMPUTATIONAL, expression=expression, value=value,
                     reason="engine evaluated the question")

    if _DEFINITION.match(q) and not _HAS_DIGIT.search(q):
        return Route(CONCEPTUAL, reason="definition request")

    if _HAS_DIGIT.search(q) and (_HAS_OPERATOR.search(q) or _WORD_PROBLEM_CUES.search(q)):
        # Looks numeric but the engine could not parse it (an unusual phrasing, or a
        # word problem outside the narrow patterns). Still computational, so the
        # answer gets verified - it just has no pre-computed value to wrap.
        return Route(COMPUTATIONAL, reason="numbers and an operator, engine could not parse")

    return Route(CONCEPTUAL, reason="no computable numeric content")

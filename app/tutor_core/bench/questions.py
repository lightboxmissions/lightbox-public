"""Question sets for the Phase 6 runs.

COMPUTATIONAL carries the correct answer, so a batch run can be graded automatically.
CONCEPTUAL cannot be graded automatically - there is no single right answer - so those
answers go to a review file for a teacher to read. That is a stated limit of the
design, not a gap in the harness.

MIXED is what the load test uses. An all-computational load test understates real load
badly, because templates answer most of those with no inference at all.
"""

# (question, correct answer as the tutor should state it)
COMPUTATIONAL = [
    ("what is 5 + 3", "8"),
    ("what is 15 + 2", "17"),
    ("what is 47 + 38", "85"),
    ("what is 128 + 264", "392"),
    ("what is 9 - 4", "5"),
    ("what is 52 - 27", "25"),
    ("what is 100 - 45", "55"),
    ("what is 9 - 12", "-3"),
    ("what is 3 x 4", "12"),
    ("what is 7 times 8", "56"),
    ("what is 12 x 12", "144"),
    ("what is 25 x 4", "100"),
    ("what is 24 divided by 6", "4"),
    ("what is 144 divided by 12", "12"),
    ("what is 7 divided by 2", "3 1/2"),
    ("what is 1/4 + 1/4", "1/2"),
    ("what is 1/2 + 1/3", "5/6"),
    ("what is 2/3 - 1/6", "1/2"),
    ("what is 2/3 x 3/4", "1/2"),
    ("what is 3/4 as a decimal", "0.75"),
    ("what is 20% of 50", "10"),
    ("what is 25% of 80", "20"),
    ("what is 15% of 200", "30"),
    ("what is 8 squared", "64"),
    ("what is 2 to the power of 5", "32"),
    ("what is the square root of 144", "12"),
    ("what is the sum of 12 and 30", "42"),
    ("what is the difference between 10 and 4", "6"),
    ("what is half of 18", "9"),
    ("what is double 7", "14"),
    ("Sarah has 5 apples and gets 3 more", "8"),
    ("Tom had 10 cookies and ate 4", "6"),
    ("there are 3 boxes of 12 pencils", "36"),
    ("24 stickers shared equally among 6 kids", "4"),
    ("what is 0.1 + 0.2", "0.3"),
    ("what is 1.5 x 2", "3"),
]

# No answer key - these need human review.
CONCEPTUAL = [
    "why do we carry the 1",
    "what is a fraction",
    "what is place value",
    "why does dividing by a fraction flip it",
    "how come 0 times anything is 0",
    "what does the denominator mean",
    "why do we need fractions",
    "when do we use division",
    "why is multiplication faster than adding over and over",
    "what does equals really mean",
    "why can't you divide by zero",
    "how do I know which fraction is bigger",
    "what is the difference between a numerator and a denominator",
    "why do we line up the decimal points",
    "what does percent mean",
    "why is any number times 1 itself",
    "what is a remainder",
    "why do we borrow when we subtract",
    "what is an even number",
    "why does the order not matter when you add",
]

# Realistic classroom mix: children ask both, and the conceptual half is the half that
# cannot be shortcut.
MIXED = [q for q, _ in COMPUTATIONAL[:10]] + CONCEPTUAL[:10]

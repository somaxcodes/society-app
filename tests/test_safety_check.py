# =============================================================================
# test_safety_check.py : tests for check_safety_flag()
# =============================================================================
# check_safety_flag(text) reads a complaint's text and answers True if it
# describes something dangerous (fire, gas leak, electric shock...) or False
# if it is an ordinary complaint.
#
# This file does not need a database or a logged-in user. It just calls one
# function with some text and checks the True/False answer. That makes it the
# simplest kind of test: "unit test" = test one small piece in isolation.
# =============================================================================

import pytest

from app.safety_check import check_safety_flag

# Ported from test_safety_check_manual.py. (complaint text, should it be flagged)
# Covers misspellings, danger words split by spaces/punctuation, pair concepts
# (lift+stuck, gas+leak, wire+spark, live+wire), word stems/tenses, and the
# false-positive guards ("live" alone, "wiring", "first", "firm", "confirm").
#
# CASES is a list. Each item is a tuple: two values in round brackets,
# ("some text", True). The first is the complaint, the second is the answer we
# EXPECT from check_safety_flag.
#
# Two kinds of mistakes are being guarded against:
#   - a missed danger (should be True but we say False)  -> someone could get hurt
#   - a false alarm (should be False but we say True)    -> staff get spammed
# That is why many cases below expect False: they look similar to dangerous
# ones but are harmless.
CASES = [
    ("There is a fyre in the parking lot", True),
    ("My kitchen sink is leaking", False),
    ("The lift is stuck between floors", True),
    ("I smell gas near the meter room", True),
    ("The lift light is flickering", False),
    ("Someone got a shok from the switchboard", True),
    ("Normal complaint about noisy neighbors", False),
    ("gasleakinbasement", True),
    ("there is a g as le ak in the kitchen", True),  # space-separated
    ("g.as le-ak smell near the meter", True),  # punctuation-separated
    ("f,i,r,e in the lobby!!", True),  # comma-separated with trailing punctuation
    ("There's a live wire hanging near the parking lot", True),
    ("I live in flat T07-1203, my tap is leaking", False),  # "live" alone must NOT trigger
    ("Water is flooding the basement", True),
    ("The ceiling collapsed in the lobby", True),
    ("Someone is trapped inside the lift", True),
    ("Exposed wire sparking near the meter room", True),
    ("Just asking about the wiring work schedule", False),  # "wire"-adjacent word alone must NOT trigger
    ("The ceiling is collapsing", True),
    ("Someone is trapping their pet lift door open", True),  # tests the trap stem, even in an odd sentence
    ("Worried someone is getting electrocuted right now", True),
    ("The security guard bled after the fall", True),
    ("someone fell in the lobby and they are injured", True),
    ("water is dripping near the electrical panel, looks dangerous", True),
    ("my tap on the first floor is leaking", False),  # "fir" must not match inside "first"
    ("Please confirm the firm date for the maintenance", False),
    ("the railing feels wobbly", True),  # danger word + structural noun
    ("my chair is wobbling", False),  # danger word alone, no structural noun
    ("ceiling is cracking", True),  # danger word + structural noun
    ("cracked my phone screen", False),  # danger word alone, no structural noun
]


# TEST: check safety flag
# One test, run once per sentence in CASES above (26 runs).
# Example: "There is a fyre in the parking lot" -> True (danger, even with the typo).
# Example: "My kitchen sink is leaking" -> False (a normal complaint).
#
# parametrize with TWO names ("text, expected"): for each tuple in CASES,
# pytest runs the test once, putting the first value in "text" and the second
# in "expected". So this one small function becomes 26 separate tests.
#
# ids=[...] gives each run a readable label (the first 50 characters of the
# text) so a failure says WHICH sentence broke instead of just "case 7".
# The [... for text, _ in CASES] part is a "list comprehension": a short way
# to build a list by looping. The "_" means "I don't need this value".
@pytest.mark.parametrize("text, expected", CASES, ids=[text[:50] for text, _ in CASES])
def test_check_safety_flag(text, expected):
    # "is" compares against the exact True/False values. The test passes only
    # if the function's answer equals what we expected for this sentence.
    assert check_safety_flag(text) is expected

"""
A plain, read-the-output-yourself script for trying out check_safety_flag()
against a set of example complaints. Not a pytest test — just run it directly
(note: no ".py" on the module name, or Python looks for a package, not a file):
  python -m test_safety_check_manual
"""

from app.safety_check import check_safety_flag

"""
(complaint text, expected result) — covers: a standalone word with a
misspelling, an ordinary complaint with no danger words, both pair
concepts (lift+stuck, gas+leak), a word only found once spaces/punctuation
are stripped (including deliberately/accidentally broken-up words meant
to evade a naive keyword match), and a plain negative case.
"""
cases = [
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
]

for text, expected in cases:
    result = check_safety_flag(text)
    status = "OK" if result == expected else "MISMATCH"
    print(f"{status}: {text!r} -> {result} (expected {expected})")

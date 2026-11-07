# Manual check of classify_complaint()'s urgency against situations where the
# right answer is clear. Calls the real Groq API, so output can vary slightly
# between runs; read the MISMATCH lines, they're the ones worth a look.
#   python -m test_urgency_manual

from app.classification import classify_complaint

cases = [
    ("tap is leaking", "Low"),
    ("my tap is lea king", "Low"),
    ("The kitchen tap in my flat drips a little bit every few seconds", "Low"),
    ("The kitchen tap in my flat is now leaking a lot, water everywhere on the floor, please fix urgently", "Medium"),
    ("URGENT!!! please fix immediately, the paint in my bedroom is peeling", "Low"),
    ("The lobby floor near the mailbox has a small crack in it", "Low"),
    ("The lift is making a loud grinding noise every time it moves", "Medium"),
    ("The hallway light outside flat T12-0408 has been flickering for a week", "Medium"),
    ("theres a dog barking n howling at night a lot", "Medium"),
    ("There is a gas leak near the meter room", "High"),
    ("Someone is stuck inside the lift between floors", "High"),
    ("Water is dripping from the ceiling onto the electrical panel in the parking garage", "High"),
    ("Someone fell in the lobby and is injured", "High"),
    ("there is smoke coming from the basement", "High"),
]

for text, expected in cases:
    got = classify_complaint(text)["urgency"]
    status = "OK" if got == expected else "MISMATCH"
    print(f"{status}: {got:<6} (expected {expected:<6}) | {text[:75]}")

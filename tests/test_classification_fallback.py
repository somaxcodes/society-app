"""
=============================================================================
test_classification_fallback.py : classify_complaint() when Groq misbehaves
=============================================================================
classify_complaint(text) asks the Groq AI for a category and urgency. The
promise of this function: the AI being down or confused must NEVER stop a
complaint from being filed. So on any failure it falls back to
    category = "other", urgency = "Medium"
and the safety check always has the last word: text that looks dangerous
(fire, gas leak...) is forced to urgency "High", whatever the AI said.

We never call the real Groq. Instead we replace the Groq class that
app/classification.py imported with a fake one that returns whatever reply
(or raises whatever error) the test chooses.

HOW THE FAKE IS BUILT (it mirrors the call chain in the real code):
    client = Groq(api_key=...)
    response = client.chat.completions.create(...)
    text = response.choices[0].message.content
SimpleNamespace is a quick way to make an object with chosen attributes, so
response.choices[0].message.content works without the real library.
=============================================================================
"""

from types import SimpleNamespace

import pytest

import app.classification
from app.classification import classify_complaint

DANGEROUS_TEXT = "There is a fire in the parking lot"  # the safety check flags this
NORMAL_TEXT = "My kitchen sink is leaking"  # the safety check does not

FALLBACK = {"category": "other", "urgency": "Medium"}


@pytest.fixture
def groq_reply(monkeypatch):
    """
    Returns a function the test calls to decide how the fake Groq behaves:
        groq_reply(content='{"category": "lift", "urgency": "Low"}')   -> returns this text
        groq_reply(error=TimeoutError("slow"))                         -> raises this error
    """
    def set_reply(content=None, error=None, choices=None):
        class FakeGroq:
            def __init__(self, api_key=None):
                # Build client.chat.completions.create(...) as nested objects.
                self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

            def create(self, **kwargs):
                if error is not None:
                    raise error
                if choices is not None:
                    return SimpleNamespace(choices=choices)
                message = SimpleNamespace(content=content)
                return SimpleNamespace(choices=[SimpleNamespace(message=message)])

        # Swap the real Groq for the fake, only for the duration of this test.
        monkeypatch.setattr(app.classification, "Groq", FakeGroq)

    return set_reply


def picked(result):
    # Just the two fields the fallback is about.
    return {"category": result["category"], "urgency": result["urgency"]}


# --- Sanity check that the fake works ---------------------------------------


"""
TEST: a good reply is used as is
A check that our fake Groq works, and that a good answer is used.
Example: Groq says {"category": "plumbing", "urgency": "Low"} -> we get plumbing / Low.
"""
def test_a_good_reply_is_used_as_is(groq_reply):
    groq_reply(content='{"category": "plumbing", "urgency": "Low"}')

    result = classify_complaint(NORMAL_TEXT)

    assert picked(result) == {"category": "plumbing", "urgency": "Low"}
    assert result["is_safety_flagged"] is False


# --- Groq fails or answers badly: fall back to other / Medium ----------------


"""
TEST: failure falls back to other and medium
Whatever goes wrong, the complaint still gets a safe default: "other" / "Medium".
Example: no internet, a timeout, plain text instead of JSON, half a JSON message,
or a missing "urgency" key -> other / Medium. (11 different failures run here.)
"""
@pytest.mark.parametrize(
    "reply",
    [
        {"error": ConnectionError("no internet")},
        {"error": TimeoutError("Groq took too long")},
        {"error": RuntimeError("model retired")},
        {"content": "I think this is a plumbing issue."},  # plain text, not JSON
        {"content": '{"category": "plumbing", "urgency": '},  # JSON cut off halfway
        {"content": ""},  # empty reply
        {"content": None},  # reply with no content at all
        {"content": '{"category": "plumbing"}'},  # JSON but the urgency key is missing
        {"content": '{"urgency": "Low"}'},  # JSON but the category key is missing
        {"content": '["plumbing", "Low"]'},  # valid JSON, but a list instead of an object
        {"choices": []},  # no answer choices returned
    ],
    ids=[
        "connection-error",
        "timeout",
        "model-retired",
        "plain-text",
        "truncated-json",
        "empty-string",
        "content-none",
        "missing-urgency",
        "missing-category",
        "json-list",
        "no-choices",
    ],
)
def test_failure_falls_back_to_other_and_medium(groq_reply, reply):
    groq_reply(**reply)  # ** unpacks the dict into named arguments

    result = classify_complaint(NORMAL_TEXT)

    assert picked(result) == FALLBACK
    assert result["is_safety_flagged"] is False


"""
TEST: failure when the client cannot even be created
The failure can happen even before we ask a question.
Example: the API key is missing, so Groq(...) itself raises an error -> other / Medium.
"""
def test_failure_when_the_client_cannot_even_be_created(monkeypatch):
    # The error happens on Groq(...) itself (for example a missing API key).
    def broken_groq(*args, **kwargs):
        raise ValueError("api_key client option must be set")

    monkeypatch.setattr(app.classification, "Groq", broken_groq)

    assert picked(classify_complaint(NORMAL_TEXT)) == FALLBACK


# --- The safety override always wins ----------------------------------------


"""
TEST: dangerous text is high even when groq fails
Danger must never be hidden by an AI failure.
Example: "There is a fire in the parking lot" while Groq is down -> category "other"
(fallback) but urgency High (not Medium), and the safety flag is on.
"""
@pytest.mark.parametrize(
    "reply",
    [
        {"error": ConnectionError("no internet")},
        {"content": "not json at all"},
        {"content": '{"category": "plumbing"}'},
    ],
    ids=["groq-down", "bad-json", "missing-key"],
)
def test_dangerous_text_is_high_even_when_groq_fails(groq_reply, reply):
    groq_reply(**reply)

    result = classify_complaint(DANGEROUS_TEXT)

    assert result["category"] == "other"  # the fallback category
    assert result["urgency"] == "High"  # NOT the fallback Medium
    assert result["is_safety_flagged"] is True


"""
TEST: dangerous text is forced high even if groq says lower
The safety check beats the AI.
Example: Groq says "Low" for the fire message -> the result is still High.
Groq's category is kept.
"""
@pytest.mark.parametrize("groq_urgency", ["Low", "Medium"])
def test_dangerous_text_is_forced_high_even_if_groq_says_lower(groq_reply, groq_urgency):
    groq_reply(content=f'{{"category": "safety", "urgency": "{groq_urgency}"}}')

    result = classify_complaint(DANGEROUS_TEXT)

    assert result["category"] == "safety"  # Groq's category is kept
    assert result["urgency"] == "High"  # only the urgency is overridden
    assert result["is_safety_flagged"] is True


"""
TEST: normal text keeps groqs urgency
The safety override must not fire for ordinary text.
Example: "Neighbours play music on weekends" and Groq says Low -> it stays Low.
"""
def test_normal_text_keeps_groqs_urgency(groq_reply):
    # Guards against the override firing for everything.
    groq_reply(content='{"category": "noise", "urgency": "Low"}')

    result = classify_complaint("Neighbours play music on weekends")

    assert result["urgency"] == "Low"
    assert result["is_safety_flagged"] is False


"""
--- Groq answers with well formed JSON, but with values we do not allow -----
The database only accepts 10 categories and 3 urgencies. If Groq invents a
value ("banana"), saving the complaint would crash with an IntegrityError.
So each value is checked against the allowed list, and a bad one falls back
on its own: category -> "other", urgency -> "Medium".
"""

ALL_CATEGORIES = [
    "plumbing", "electrical", "lift", "security", "cleaning",
    "safety", "structural", "parking", "noise", "other",
]


"""
TEST: an unknown category falls back to other
Example: Groq says {"category": "banana", "urgency": "High"} ->
category becomes "other". The valid urgency "High" is kept.
"""
@pytest.mark.parametrize(
    "bad_category",
    ["banana", "Plumbing", "", " lift", "lifts", None, 5, ["lift"]],
    ids=["unknown-word", "wrong-capital", "empty", "leading-space", "plural", "null", "number", "list"],
)
def test_unknown_category_falls_back_to_other(groq_reply, bad_category):
    import json

    groq_reply(content=json.dumps({"category": bad_category, "urgency": "High"}))

    result = classify_complaint(NORMAL_TEXT)

    assert result["category"] == "other"
    assert result["urgency"] == "High"  # only the bad field is replaced


"""
TEST: an unknown urgency falls back to Medium
Example: Groq says {"category": "lift", "urgency": "Urgent"} ->
urgency becomes "Medium". The valid category "lift" is kept.
"""
@pytest.mark.parametrize(
    "bad_urgency",
    ["Urgent", "high", "HIGH", "", None, 3],
    ids=["unknown-word", "lowercase", "uppercase", "empty", "null", "number"],
)
def test_unknown_urgency_falls_back_to_medium(groq_reply, bad_urgency):
    import json

    groq_reply(content=json.dumps({"category": "lift", "urgency": bad_urgency}))

    result = classify_complaint(NORMAL_TEXT)

    assert result["category"] == "lift"
    assert result["urgency"] == "Medium"


"""
TEST: both values unknown
Example: {"category": "banana", "urgency": "Urgent"} -> other / Medium,
exactly the same as when Groq is down.
"""
def test_unknown_category_and_urgency_give_the_standard_fallback(groq_reply):
    groq_reply(content='{"category": "banana", "urgency": "Urgent"}')

    assert picked(classify_complaint(NORMAL_TEXT)) == FALLBACK


"""
TEST: every allowed value still passes through
Example: Groq says "parking" / "Low" -> we get "parking" / "Low".
This makes sure the new check does not reject valid answers (all 10 categories
and all 3 urgencies are tried).
"""
@pytest.mark.parametrize("category", ALL_CATEGORIES)
@pytest.mark.parametrize("urgency", ["Low", "Medium", "High"])
def test_every_valid_category_and_urgency_is_kept(groq_reply, category, urgency):
    groq_reply(content=f'{{"category": "{category}", "urgency": "{urgency}"}}')

    result = classify_complaint(NORMAL_TEXT)

    assert picked(result) == {"category": category, "urgency": urgency}


"""
TEST: dangerous text with an unknown category
Example: "There is a fire in the parking lot" and Groq says category "banana" ->
category "other", but urgency is still forced to High by the safety check.
"""
def test_dangerous_text_with_unknown_category_is_still_high(groq_reply):
    groq_reply(content='{"category": "banana", "urgency": "Low"}')

    result = classify_complaint(DANGEROUS_TEXT)

    assert result["category"] == "other"
    assert result["urgency"] == "High"
    assert result["is_safety_flagged"] is True


"""
TEST: filing a complaint no longer crashes on an unknown category (full trip)
Example: a resident submits "Gate lock is broken", Groq answers "banana".
Before the fix this was a database IntegrityError (a 500 error). Now the
complaint is saved as category "other".
"""
def test_filing_a_complaint_survives_an_unknown_category(groq_reply, resident_client, db_session):
    from app.models import Complaint

    groq_reply(content='{"category": "banana", "urgency": "Urgent"}')

    response = resident_client.post(
        "/complaints/new", data={"description": "Gate lock is broken"}, follow_redirects=False
    )

    assert response.status_code == 303
    saved = db_session.query(Complaint).one()
    assert (saved.category, saved.urgency) == ("other", "Medium")


"""
TEST: the allowed lists match the rest of the app
Example: if someone adds a category "garden" to the staff page list but forgets
the classifier list (or the reverse), this test fails and tells us.
Every allowed category and urgency must also really be accepted by the database.
"""
def test_allowed_values_match_the_rest_of_the_app(db_session, flat):
    from app.main import ALL_CATEGORIES as STAFF_PAGE_CATEGORIES
    from app.models import Complaint

    assert set(app.classification.VALID_CATEGORIES) == set(STAFF_PAGE_CATEGORIES)
    assert set(app.classification.VALID_URGENCIES) == {"Low", "Medium", "High"}

    for category in app.classification.VALID_CATEGORIES:
        for urgency in app.classification.VALID_URGENCIES:
            db_session.add(
                Complaint(flat_id=flat.id, description="x", category=category, urgency=urgency, status="Open")
            )
    db_session.commit()  # would raise IntegrityError if the database disagreed

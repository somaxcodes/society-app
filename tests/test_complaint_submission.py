"""
=============================================================================
test_complaint_submission.py : tests for POST /complaints/new (+ /complaints)
=============================================================================
When a resident submits a complaint, the route calls two functions that talk
to the Groq AI service:
  classify_complaint(text)             -> decides category / urgency / safety
  find_duplicate(db, flat, cat, text)  -> finds an existing similar complaint

Tests must NEVER call the real AI (slow, costs money, answers can change,
and it fails without internet). So we replace both functions with fakes.

MONKEYPATCH: pytest's built-in "monkeypatch" fixture temporarily swaps
something for something else, and puts the original back after the test.
    monkeypatch.setattr(app.main, "classify_complaint", fake_function)
We patch the name inside app.main (not app.classification) because main.py
did "from app.classification import classify_complaint", which made its own
copy of the name. The route looks the name up in app.main, so that is the
one to replace.
=============================================================================
"""

import pytest

import app.main
from app.models import Complaint, Flat

MAX_LENGTH_ERROR = "Please enter a description between 1 and 1000 characters"


class FakeAI:
    # Remembers what the route asked and returns whatever the test chose.
    def __init__(self):
        self.classification = {"category": "lift", "urgency": "Medium", "is_safety_flagged": False}
        self.duplicate_id = None  # what the fake find_duplicate returns
        self.classify_calls = []  # every text classify_complaint was called with
        self.duplicate_calls = []  # every (category, text) find_duplicate was called with


"""
autouse=True means: every test in this file gets this fixture automatically,
even if it does not list it as a parameter. That guarantees no test here can
reach the real Groq API by accident. A test that wants to inspect or change
the fake simply lists "fake_ai" as a parameter to get the same object.
"""
@pytest.fixture(autouse=True)
def fake_ai(monkeypatch):
    fake = FakeAI()

    def fake_classify_complaint(text):
        fake.classify_calls.append(text)
        return dict(fake.classification)  # dict(...) hands back a copy

    def fake_find_duplicate(db_session, flat, category, text, exclude_id=None):
        fake.duplicate_calls.append((category, text))
        return fake.duplicate_id

    monkeypatch.setattr(app.main, "classify_complaint", fake_classify_complaint)
    monkeypatch.setattr(app.main, "find_duplicate", fake_find_duplicate)
    return fake


def submit(resident_client, description):
    return resident_client.post(
        "/complaints/new", data={"description": description}, follow_redirects=False
    )


def all_complaints(db_session):
    return db_session.query(Complaint).all()


# --- A valid submission ------------------------------------------------------


"""
TEST: valid complaint is saved and redirects
A normal complaint is saved and the resident is sent to their list.
Example: "The lift in tower 7 keeps stopping" -> saved as Open under the resident's
own flat, then redirect to /complaints?submitted=1.
"""
def test_valid_complaint_is_saved_and_redirects(resident_client, db_session, resident_user, fake_ai):
    response = submit(resident_client, "The lift in tower 7 keeps stopping")

    assert response.status_code == 303
    assert response.headers["location"] == "/complaints?submitted=1"

    complaints = all_complaints(db_session)
    assert len(complaints) == 1
    saved = complaints[0]
    assert saved.description == "The lift in tower 7 keeps stopping"
    assert saved.flat_id == resident_user.flat_id  # filed under the resident's own flat
    assert saved.status == "Open"
    assert saved.linked_to_id is None  # the fake found no duplicate


"""
TEST: category urgency and safety flag come from the classifier
The saved values are whatever the classifier decided.
Example: the (fake) classifier says electrical / High / safety flagged -> the saved
complaint has exactly those values.
"""
def test_category_urgency_and_safety_flag_come_from_the_classifier(resident_client, db_session, fake_ai):
    fake_ai.classification = {"category": "electrical", "urgency": "High", "is_safety_flagged": True}

    submit(resident_client, "Sparks from the switchboard")

    saved = all_complaints(db_session)[0]
    assert saved.category == "electrical"
    assert saved.urgency == "High"
    assert saved.is_safety_flagged is True


"""
TEST: description is trimmed before classifying and saving
Extra spaces and new lines at the ends are removed.
Example: "   Water leaking from ceiling   " is saved as "Water leaking from ceiling".
"""
def test_description_is_trimmed_before_classifying_and_saving(resident_client, db_session, fake_ai):
    submit(resident_client, "   Water leaking from ceiling   \n")

    assert fake_ai.classify_calls == ["Water leaking from ceiling"]
    assert all_complaints(db_session)[0].description == "Water leaking from ceiling"


"""
TEST: a duplicate found by the fake links the new complaint
If find_duplicate finds a similar complaint, the new one is linked to it.
Example: old "Lift stuck" (Low) and new "Lift is stuck again" (High) -> the new one
points at the old one, and the old one is raised to High.
"""
def test_a_duplicate_found_by_the_fake_links_the_new_complaint(resident_client, db_session, flat, fake_ai):
    existing = Complaint(
        flat_id=flat.id, description="Lift stuck", category="lift", urgency="Low", status="Open"
    )
    db_session.add(existing)
    db_session.commit()
    fake_ai.duplicate_id = existing.id  # the fake find_duplicate points at it
    fake_ai.classification = {"category": "lift", "urgency": "High", "is_safety_flagged": False}

    submit(resident_client, "Lift is stuck again")

    new = db_session.query(Complaint).filter(Complaint.id != existing.id).one()
    assert new.linked_to_id == existing.id
    db_session.refresh(existing)
    assert existing.urgency == "High"  # escalated, as in test_complaint_logic.py


"""
TEST: find duplicate receives the category from the classifier
The category from step 1 (classify) is passed to step 2 (find duplicate).
Example: the classifier says "plumbing" -> find_duplicate is called with "plumbing".
"""
def test_find_duplicate_receives_the_category_from_the_classifier(resident_client, fake_ai):
    fake_ai.classification = {"category": "plumbing", "urgency": "Low", "is_safety_flagged": False}

    submit(resident_client, "Tap dripping")

    assert fake_ai.duplicate_calls == [("plumbing", "Tap dripping")]


# --- Rejected submissions ----------------------------------------------------


"""
TEST: empty text is rejected
Empty or blank text is refused with a friendly message.
Example: "", "   " or only new lines -> the form shows again with an error,
nothing is saved, and the AI is not called.
"""
@pytest.mark.parametrize("bad_text", ["", "   ", "\n\t  \n"], ids=["empty", "spaces", "whitespace-only"])
def test_empty_text_is_rejected(resident_client, db_session, fake_ai, bad_text):
    response = submit(resident_client, bad_text)

    assert response.status_code == 200  # form shown again, not a redirect
    assert MAX_LENGTH_ERROR in response.text
    assert all_complaints(db_session) == []
    assert fake_ai.classify_calls == []  # we do not waste an AI call on garbage


"""
TEST: missing description field is rejected
Even if the form field is missing completely, the user gets the friendly error.
Example: a request with no "description" at all -> error message, nothing saved.
"""
def test_missing_description_field_is_rejected(resident_client, db_session):
    # No "description" key at all in the form data.
    response = resident_client.post("/complaints/new", data={}, follow_redirects=False)

    assert response.status_code == 200
    assert MAX_LENGTH_ERROR in response.text
    assert all_complaints(db_session) == []


"""
TEST: text over 1000 characters is rejected
Too long is refused.
Example: 1001 letters -> error message, nothing saved.
"""
def test_text_over_1000_characters_is_rejected(resident_client, db_session, fake_ai):
    response = submit(resident_client, "a" * 1001)  # "a" * 1001 repeats "a" 1001 times

    assert response.status_code == 200
    assert MAX_LENGTH_ERROR in response.text
    assert all_complaints(db_session) == []
    assert fake_ai.classify_calls == []


"""
TEST: text of exactly 1000 characters is accepted
Exactly the limit is still fine (an edge case).
Example: 1000 letters -> saved.
"""
def test_text_of_exactly_1000_characters_is_accepted(resident_client, db_session):
    # Boundary test: 1000 is the largest allowed length.
    response = submit(resident_client, "a" * 1000)

    assert response.status_code == 303
    assert len(all_complaints(db_session)) == 1


"""
TEST: length limit applies after trimming
Spaces at the ends do not count towards the limit.
Example: 1000 letters with 50 spaces on each side -> accepted.
"""
def test_length_limit_applies_after_trimming(resident_client, db_session):
    # 1000 real characters plus 50 spaces of padding: still fine, because the
    # route strips the spaces before measuring.
    response = submit(resident_client, "  " * 25 + "a" * 1000 + "  " * 25)

    assert response.status_code == 303
    assert len(all_complaints(db_session)) == 1


# --- Who may submit ----------------------------------------------------------


"""
TEST: staff cannot submit a complaint
Only residents file complaints.
Example: a staff member posts "Lift broken" -> 403 and nothing is saved.
"""
def test_staff_cannot_submit_a_complaint(staff_client, db_session, fake_ai):
    response = staff_client.post(
        "/complaints/new", data={"description": "Lift broken"}, follow_redirects=False
    )

    assert response.status_code == 403
    assert all_complaints(db_session) == []
    assert fake_ai.classify_calls == []


"""
TEST: anonymous cannot submit a complaint
You must be logged in.
Example: a visitor who is not logged in posts "Lift broken" -> 401 and nothing is saved.
"""
def test_anonymous_cannot_submit_a_complaint(client, db_session):
    response = client.post("/complaints/new", data={"description": "Lift broken"}, follow_redirects=False)

    assert response.status_code == 401
    assert all_complaints(db_session) == []


# --- A resident only sees their own complaints ------------------------------


"""
TEST: resident only sees their own complaints
Residents must not see their neighbours' complaints.
Example: flat A wrote "MY OWN COMPLAINT", flat B wrote "NEIGHBOUR PRIVATE COMPLAINT".
Flat A's /complaints page shows only its own.
"""
def test_resident_only_sees_their_own_complaints(resident_client, db_session, resident_user):
    # A second flat, belonging to a different household, with its own complaint.
    other_flat = Flat(flat_number="T12-0408", owner_name="Other Owner", area_sqft=900, upi_id="other@upi")
    db_session.add(other_flat)
    db_session.flush()
    db_session.add(
        Complaint(
            flat_id=other_flat.id,
            description="NEIGHBOUR PRIVATE COMPLAINT",
            category="noise",
            urgency="Low",
            status="Open",
        )
    )
    db_session.add(
        Complaint(
            flat_id=resident_user.flat_id,
            description="MY OWN COMPLAINT",
            category="lift",
            urgency="Low",
            status="Open",
        )
    )
    db_session.commit()

    response = resident_client.get("/complaints")

    assert response.status_code == 200
    assert "MY OWN COMPLAINT" in response.text
    assert "NEIGHBOUR PRIVATE COMPLAINT" not in response.text


"""
TEST: a newly submitted complaint shows up with the success banner
The full trip, like a real user.
Example: submit "Gate lock is broken" -> the list page shows "Your complaint has been
submitted" and the new complaint.
"""
def test_a_newly_submitted_complaint_shows_up_with_the_success_banner(resident_client):
    # Default follow_redirects=True: land on /complaints?submitted=1 like a browser.
    response = resident_client.post("/complaints/new", data={"description": "Gate lock is broken"})

    assert response.status_code == 200
    assert "Your complaint has been submitted" in response.text
    assert "Gate lock is broken" in response.text

"""
=============================================================================
test_duplicate_filters.py : which complaints may be considered duplicates?
=============================================================================
find_duplicate(db, flat, category, text) works in two stages:
  1. A cheap database FILTER picks "candidates": complaints with the same
     category, in the same tower, still open, created within the last 7 days.
  2. For each candidate (oldest first) it asks Groq "same problem? yes/no".

These tests check stage 1: a complaint that fails any filter must never even
be shown to Groq. The fake Groq answers "yes" to everything by default, so
the ONLY thing that can keep a complaint from being returned is the filter.
Seeing zero Groq calls proves the candidate was excluded before asking.

Flat numbers look like "T07-1203": "T07" is the tower. The conftest "flat"
fixture is T07-1203, so T07-0501 is the same tower and T12-0408 is another.
=============================================================================
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

import app.classification
from app.classification import find_duplicate
from app.models import Complaint, Flat

NEW_TEXT = "Lift is making a loud noise again"


class GroqSpy:
    # Remembers every question asked and answers from a prepared list.
    def __init__(self):
        self.answers = []  # replies to give, in order; once used up, say "yes"
        self.prompts = []  # the "Complaint A / Complaint B" text of each question


@pytest.fixture
def groq(monkeypatch):
    spy = GroqSpy()

    class FakeGroq:
        def __init__(self, api_key=None):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def create(self, **kwargs):
            # kwargs["messages"][-1] is the user message holding both complaints.
            spy.prompts.append(kwargs["messages"][-1]["content"])
            reply = spy.answers.pop(0) if spy.answers else "yes"
            if isinstance(reply, Exception):
                raise reply
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=reply))])

    monkeypatch.setattr(app.classification, "Groq", FakeGroq)
    return spy


def add_flat(db, flat_number):
    flat = Flat(flat_number=flat_number, owner_name="Owner", area_sqft=900, upi_id=f"{flat_number}@upi")
    db.add(flat)
    db.flush()
    return flat


def add_complaint(db, flat, category="lift", status="Open", age_days=0, description="Lift making noise"):
    complaint = Complaint(
        flat_id=flat.id,
        description=description,
        category=category,
        urgency="Medium",
        status=status,
        # utcnow() minus N days: pretend the complaint was filed N days ago.
        created_at=datetime.utcnow() - timedelta(days=age_days),
    )
    db.add(complaint)
    db.commit()
    return complaint


# --- Baseline: a candidate that passes every filter --------------------------


"""
TEST: matching candidate is returned when groq says yes
Baseline: one fitting complaint, and Groq says "same problem" -> its id is returned.
Example: an open lift complaint from today, in the same tower -> that complaint's id.
"""
def test_matching_candidate_is_returned_when_groq_says_yes(db_session, flat, groq):
    candidate = add_complaint(db_session, flat)

    assert find_duplicate(db_session, flat, "lift", NEW_TEXT) == candidate.id
    assert len(groq.prompts) == 1  # Groq was asked exactly once


"""
TEST: candidate in the same tower but a different flat is allowed
The tower must match, not the exact flat.
Example: new complaint from T07-1203, old one from T07-0501 -> allowed (both are tower T07).
"""
def test_candidate_in_the_same_tower_but_a_different_flat_is_allowed(db_session, flat, groq):
    neighbour = add_flat(db_session, "T07-0501")
    candidate = add_complaint(db_session, neighbour)

    assert find_duplicate(db_session, flat, "lift", NEW_TEXT) == candidate.id


"""
TEST: in progress complaints are still candidates
"In Progress" counts as still open.
Example: an In Progress lift complaint can still be a duplicate.
"""
def test_in_progress_complaints_are_still_candidates(db_session, flat, groq):
    candidate = add_complaint(db_session, flat, status="In Progress")

    assert find_duplicate(db_session, flat, "lift", NEW_TEXT) == candidate.id


# --- Filter 1: different tower -----------------------------------------------


"""
TEST: complaint from a different tower is excluded
A different tower means a different problem.
Example: new complaint from T07, old lift complaint from T12 -> no duplicate,
and Groq is never even asked.
"""
def test_complaint_from_a_different_tower_is_excluded(db_session, flat, groq):
    other_tower_flat = add_flat(db_session, "T12-0408")
    add_complaint(db_session, other_tower_flat)  # same category, open, recent

    assert find_duplicate(db_session, flat, "lift", NEW_TEXT) is None
    assert groq.prompts == []  # filtered out before Groq was ever asked


"""
TEST: only the same tower candidate is shown to groq
Only the fitting complaint is sent to Groq.
Example: one from tower T12 and one from tower T07 exist -> Groq only sees the T07 one.
"""
def test_only_the_same_tower_candidate_is_shown_to_groq(db_session, flat, groq):
    other_tower_flat = add_flat(db_session, "T12-0408")
    add_complaint(db_session, other_tower_flat, description="OTHER TOWER COMPLAINT")
    same_tower = add_complaint(db_session, flat, description="SAME TOWER COMPLAINT")

    assert find_duplicate(db_session, flat, "lift", NEW_TEXT) == same_tower.id
    assert len(groq.prompts) == 1
    assert "SAME TOWER COMPLAINT" in groq.prompts[0]
    assert "OTHER TOWER COMPLAINT" not in groq.prompts[0]


# --- Filter 2: older than 7 days ---------------------------------------------


"""
TEST: complaint older than 7 days is excluded
Old complaints are not duplicates.
Example: a lift complaint from 8 days ago -> ignored.
"""
def test_complaint_older_than_7_days_is_excluded(db_session, flat, groq):
    add_complaint(db_session, flat, age_days=8)

    assert find_duplicate(db_session, flat, "lift", NEW_TEXT) is None
    assert groq.prompts == []


"""
TEST: complaint just inside 7 days is included
An edge case: just under the limit still counts.
Example: a complaint from 6 days ago -> still a candidate.
"""
def test_complaint_just_inside_7_days_is_included(db_session, flat, groq):
    # Boundary check from the other side: 6 days old is still recent enough.
    candidate = add_complaint(db_session, flat, age_days=6)

    assert find_duplicate(db_session, flat, "lift", NEW_TEXT) == candidate.id


"""
TEST: old complaint is skipped but a recent one still matches
The old one is skipped and the recent one is still found.
Example: complaints from 10 days ago and 1 day ago -> the 1-day-old one is returned.
"""
def test_old_complaint_is_skipped_but_a_recent_one_still_matches(db_session, flat, groq):
    add_complaint(db_session, flat, age_days=10, description="OLD COMPLAINT")
    recent = add_complaint(db_session, flat, age_days=1, description="RECENT COMPLAINT")

    assert find_duplicate(db_session, flat, "lift", NEW_TEXT) == recent.id
    assert len(groq.prompts) == 1
    assert "OLD COMPLAINT" not in groq.prompts[0]


# --- Filter 3: resolved complaints -------------------------------------------


"""
TEST: resolved complaint is excluded
A fixed problem cannot have new duplicates.
Example: a Resolved lift complaint from today -> ignored.
"""
def test_resolved_complaint_is_excluded(db_session, flat, groq):
    add_complaint(db_session, flat, status="Resolved")

    assert find_duplicate(db_session, flat, "lift", NEW_TEXT) is None
    assert groq.prompts == []


# --- Filter 4: category ------------------------------------------------------


"""
TEST: complaint with a different category is excluded
The category must be the same.
Example: an old "plumbing" complaint, a new "lift" one -> not a duplicate.
"""
def test_complaint_with_a_different_category_is_excluded(db_session, flat, groq):
    add_complaint(db_session, flat, category="plumbing")

    assert find_duplicate(db_session, flat, "lift", NEW_TEXT) is None
    assert groq.prompts == []


# --- Everything excluded at once --------------------------------------------


"""
TEST: every kind of non candidate together gives none
All the rules together.
Example: wrong tower, too old, resolved and wrong category, all at once -> None,
and Groq is never asked.
"""
def test_every_kind_of_non_candidate_together_gives_none(db_session, flat, groq):
    add_complaint(db_session, add_flat(db_session, "T12-0408"))  # wrong tower
    add_complaint(db_session, flat, age_days=9)  # too old
    add_complaint(db_session, flat, status="Resolved")  # resolved
    add_complaint(db_session, flat, category="noise")  # wrong category

    assert find_duplicate(db_session, flat, "lift", NEW_TEXT) is None
    assert groq.prompts == []


# --- Ordering, Groq's answer, exclude_id and errors --------------------------


"""
TEST: oldest candidate is asked about first
The oldest matching complaint wins, so all duplicates point to the original.
Example: complaints from 3 days ago and 1 day ago; Groq says yes to both ->
the 3-day-old one is returned.
"""
def test_oldest_candidate_is_asked_about_first(db_session, flat, groq):
    older = add_complaint(db_session, flat, age_days=3, description="OLDER")
    add_complaint(db_session, flat, age_days=1, description="NEWER")

    assert find_duplicate(db_session, flat, "lift", NEW_TEXT) == older.id
    assert len(groq.prompts) == 1  # stopped at the first "yes"


"""
TEST: groq saying no to everything gives none
If Groq says "different problem" every time, there is no duplicate.
Example: 2 candidates, both answered "no" -> None (both were checked).
"""
def test_groq_saying_no_to_everything_gives_none(db_session, flat, groq):
    add_complaint(db_session, flat, age_days=2)
    add_complaint(db_session, flat, age_days=1)
    groq.answers = ["no", "no"]

    assert find_duplicate(db_session, flat, "lift", NEW_TEXT) is None
    assert len(groq.prompts) == 2  # both candidates were checked


"""
TEST: a no then a yes returns the second candidate
It keeps going until it gets a yes.
Example: the first answer is "no", the second is "Yes\n" -> the second complaint is returned.
(The answer is trimmed and made lowercase first.)
"""
def test_a_no_then_a_yes_returns_the_second_candidate(db_session, flat, groq):
    add_complaint(db_session, flat, age_days=2)
    second = add_complaint(db_session, flat, age_days=1)
    groq.answers = ["no", "Yes\n"]  # answer is cleaned up: trimmed and lower-cased

    assert find_duplicate(db_session, flat, "lift", NEW_TEXT) == second.id


"""
TEST: exclude id removes that complaint from the candidates
A complaint can be left out of its own search.
Example: the only candidate has id 5 and exclude_id=5 -> None.
"""
def test_exclude_id_removes_that_complaint_from_the_candidates(db_session, flat, groq):
    only = add_complaint(db_session, flat)

    assert find_duplicate(db_session, flat, "lift", NEW_TEXT, exclude_id=only.id) is None
    assert groq.prompts == []


"""
TEST: a groq error gives none instead of crashing
If Groq fails, filing the complaint must still work.
Example: Groq raises ConnectionError -> the answer is None (no duplicate), no crash.
"""
def test_a_groq_error_gives_none_instead_of_crashing(db_session, flat, groq):
    add_complaint(db_session, flat)
    groq.answers = [ConnectionError("Groq is down")]

    assert find_duplicate(db_session, flat, "lift", NEW_TEXT) is None

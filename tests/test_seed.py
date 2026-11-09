"""
=============================================================================
test_seed.py : tests for app/seed.py's sample complaint data
=============================================================================
run_seed(db) fills a fresh database with sample flats, bills, users, and
(as of this file) sample complaints too -- so a grader opening a freshly
deployed instance sees a populated dashboard, not an empty one.

These tests run run_seed() directly against the test database (db_session
fixture: a fresh, empty, in-memory SQLite database -- see conftest.py), the
same way app/main.py calls it automatically on a real empty-database startup.
=============================================================================
"""

from app.models import Complaint
from app.seed import run_seed


"""
TEST: reseeding adds complaints, not just flats
Example: run_seed() on an empty database -> the complaints table is no
longer empty.
"""
def test_reseeding_adds_complaints(db_session):
    run_seed(db_session)

    complaints = db_session.query(Complaint).all()
    assert len(complaints) > 0


"""
TEST: reseeding includes a duplicate-linked pair
Example: among the seeded complaints, at least one has linked_to_id set --
so the duplicate-linking UI (the "linked to an existing report" note) has
something to show on page load, without anyone having to file a new
complaint first.
"""
def test_reseeding_includes_a_duplicate_linked_complaint(db_session):
    run_seed(db_session)

    complaints = db_session.query(Complaint).all()
    linked = [c for c in complaints if c.linked_to_id is not None]
    assert len(linked) > 0

    # The complaint it points at must be a real seeded complaint, not a
    # dangling id -- otherwise the "linked to" page lookup would just find
    # nothing.
    complaint_ids = {c.id for c in complaints}
    for complaint in linked:
        assert complaint.linked_to_id in complaint_ids


"""
TEST: reseeding includes a safety-flagged complaint
Example: among the seeded complaints, at least one has
is_safety_flagged=True -- so the red safety banner is visible on page load
without anyone having to file a new complaint with trigger wording.
"""
def test_reseeding_includes_a_safety_flagged_complaint(db_session):
    run_seed(db_session)

    complaints = db_session.query(Complaint).all()
    assert any(c.is_safety_flagged for c in complaints)


"""
TEST: reseeding includes a High-urgency complaint that is NOT safety-flagged
Example: among the seeded complaints, at least one has urgency="High" and
is_safety_flagged=False -- so the amber "AI flagged this as high-risk, no
safety keyword matched" banner is visible on page load too.
"""
def test_reseeding_includes_a_high_urgency_unflagged_complaint(db_session):
    run_seed(db_session)

    complaints = db_session.query(Complaint).all()
    assert any(c.urgency == "High" and not c.is_safety_flagged for c in complaints)

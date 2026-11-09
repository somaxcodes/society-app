"""
=============================================================================
test_complaint_update.py : tests for POST /staff/complaints/{id}/update
=============================================================================
Staff use this route to change a complaint's category and status.

Rules being tested:
  1. resolved_at (when the complaint became Resolved):
       - SET when status changes from Open/In Progress to Resolved
       - LEFT ALONE when an already Resolved complaint is saved again
       - CLEARED (back to None) when a complaint leaves Resolved (reopened)
  2. An invalid category or status is rejected: nothing is saved.
  3. If the status really changed AND the complaint has linked duplicates,
     the redirect carries ?status_changed_id=... so the page can show a
     reminder banner. Otherwise it is a plain redirect.
=============================================================================
"""

from datetime import datetime

from app.models import Complaint


def make_complaint(db, flat, status="Open", category="lift", linked_to_id=None, resolved_at=None):
    complaint = Complaint(
        flat_id=flat.id,
        description="Lift making a noise",
        category=category,
        urgency="Medium",
        status=status,
        linked_to_id=linked_to_id,
        resolved_at=resolved_at,
    )
    db.add(complaint)
    db.commit()
    return complaint


def post_update(staff_client, complaint, category=None, status=None):
    """
    Sends the staff "update" form. If a value is not given, we resend the
    complaint's current one, so a test only has to name what it changes.
    "x or y" gives x if x is not None/empty, otherwise y.
    """
    return staff_client.post(
        f"/staff/complaints/{complaint.id}/update",
        data={"category": category or complaint.category, "status": status or complaint.status},
        follow_redirects=False,  # keep the redirect so we can read where it points
    )


# --- resolved_at: set / untouched / cleared ----------------------------------


"""
TEST: resolving an open complaint sets resolved at
Marking a complaint Resolved stamps the time.
Example: Open -> Resolved at 3pm -> resolved_at is "now" (about 3pm).
"""
def test_resolving_an_open_complaint_sets_resolved_at(staff_client, db_session, flat):
    complaint = make_complaint(db_session, flat, status="Open")

    post_update(staff_client, complaint, status="Resolved")

    db_session.refresh(complaint)
    assert complaint.status == "Resolved"
    assert complaint.resolved_at is not None
    # The timestamp should be "just now": less than a minute old.
    assert (datetime.utcnow() - complaint.resolved_at).total_seconds() < 60


"""
TEST: resolving an in progress complaint sets resolved at
Same, when it was In Progress before.
Example: In Progress -> Resolved -> resolved_at is set.
"""
def test_resolving_an_in_progress_complaint_sets_resolved_at(staff_client, db_session, flat):
    complaint = make_complaint(db_session, flat, status="In Progress")

    post_update(staff_client, complaint, status="Resolved")

    db_session.refresh(complaint)
    assert complaint.resolved_at is not None


"""
TEST: saving an already resolved complaint keeps the old resolved at
Saving again must not move the original time.
Example: resolved on 1 Jan; staff later fix the category only -> resolved_at is still 1 Jan.
"""
def test_saving_an_already_resolved_complaint_keeps_the_old_resolved_at(staff_client, db_session, flat):
    # A fixed date far in the past, so "was it overwritten with now?" is obvious.
    original_time = datetime(2026, 1, 1, 12, 0, 0)
    complaint = make_complaint(db_session, flat, status="Resolved", resolved_at=original_time)

    # Status stays Resolved; only the category changes.
    post_update(staff_client, complaint, category="electrical", status="Resolved")

    db_session.refresh(complaint)
    assert complaint.category == "electrical"  # the save did happen
    assert complaint.resolved_at == original_time  # but the timestamp did not move


"""
TEST: reopening a resolved complaint clears resolved at
If a complaint is reopened, the "resolved" time is wiped.
Example: Resolved -> Open -> resolved_at becomes None.
"""
def test_reopening_a_resolved_complaint_clears_resolved_at(staff_client, db_session, flat):
    complaint = make_complaint(db_session, flat, status="Resolved", resolved_at=datetime(2026, 1, 1))

    post_update(staff_client, complaint, status="Open")

    db_session.refresh(complaint)
    assert complaint.status == "Open"
    assert complaint.resolved_at is None


"""
TEST: moving open to in progress leaves resolved at empty
Only the Resolved status sets the time.
Example: Open -> In Progress -> resolved_at stays None.
"""
def test_moving_open_to_in_progress_leaves_resolved_at_empty(staff_client, db_session, flat):
    complaint = make_complaint(db_session, flat, status="Open")

    post_update(staff_client, complaint, status="In Progress")

    db_session.refresh(complaint)
    assert complaint.status == "In Progress"
    assert complaint.resolved_at is None


"""
TEST: resolve reopen resolve gets a fresh timestamp
After resolve, reopen, resolve again, the time is the NEW one.
Example: resolved 1 Jan, reopened, resolved again today -> resolved_at is today, not 1 Jan.
"""
def test_resolve_reopen_resolve_gets_a_fresh_timestamp(staff_client, db_session, flat):
    # Resolved long ago, then reopened, then resolved again: the final
    # resolved_at must be the NEW time, not the old one.
    complaint = make_complaint(db_session, flat, status="Resolved", resolved_at=datetime(2026, 1, 1))

    post_update(staff_client, complaint, status="Open")
    post_update(staff_client, complaint, status="Resolved")

    db_session.refresh(complaint)
    assert complaint.resolved_at > datetime(2026, 1, 1)


# --- Invalid input is rejected ----------------------------------------------


"""
TEST: invalid category is rejected and nothing changes
A made-up category stops the whole update.
Example: category "not-a-category" with status Resolved -> redirect back,
and neither the category nor the status changes.
"""
def test_invalid_category_is_rejected_and_nothing_changes(staff_client, db_session, flat):
    complaint = make_complaint(db_session, flat, status="Open", category="lift")

    # Even though the status value is valid, the bad category must stop the
    # WHOLE update (status must not change either).
    response = post_update(staff_client, complaint, category="not-a-category", status="Resolved")

    assert response.status_code == 303
    assert response.headers["location"] == "/staff/complaints"
    db_session.refresh(complaint)
    assert complaint.category == "lift"
    assert complaint.status == "Open"
    assert complaint.resolved_at is None


"""
TEST: invalid status is rejected and nothing changes
A made-up status stops the whole update.
Example: status "Finished" (not a real status) with a valid new category -> nothing is saved.
"""
def test_invalid_status_is_rejected_and_nothing_changes(staff_client, db_session, flat):
    complaint = make_complaint(db_session, flat, status="Open", category="lift")

    response = post_update(staff_client, complaint, category="electrical", status="Finished")

    assert response.status_code == 303
    assert response.headers["location"] == "/staff/complaints"
    db_session.refresh(complaint)
    assert complaint.category == "lift"  # the valid category was NOT applied either
    assert complaint.status == "Open"


"""
TEST: updating a complaint that does not exist just redirects
A wrong id must not crash the page.
Example: updating complaint number 9999 (it does not exist) -> a plain redirect.
"""
def test_updating_a_complaint_that_does_not_exist_just_redirects(staff_client):
    # No complaint with id 9999 exists. The route should redirect, not crash.
    response = staff_client.post(
        "/staff/complaints/9999/update",
        data={"category": "lift", "status": "Resolved"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/staff/complaints"


# --- Sibling reminder redirect ----------------------------------------------


"""
TEST: status change on a clustered complaint redirects with reminder
Changing the status of a complaint that has duplicates adds a reminder to the redirect.
Example: resolve anchor A (B is its duplicate) -> redirect to
/staff/complaints?status_changed_id=<A's id> so staff are told to check B.
"""
def test_status_change_on_a_clustered_complaint_redirects_with_reminder(staff_client, db_session, flat):
    anchor = make_complaint(db_session, flat, status="Open")
    make_complaint(db_session, flat, status="Open", linked_to_id=anchor.id)  # a duplicate

    response = post_update(staff_client, anchor, status="Resolved")

    assert response.headers["location"] == f"/staff/complaints?status_changed_id={anchor.id}"


"""
TEST: status change on a duplicate also redirects with reminder
The reminder works from the duplicate's side too.
Example: B (a duplicate of A) goes to In Progress -> the reminder redirect appears.
"""
def test_status_change_on_a_duplicate_also_redirects_with_reminder(staff_client, db_session, flat):
    # The reminder works from the duplicate's side too (its sibling is the anchor).
    anchor = make_complaint(db_session, flat, status="Open")
    duplicate = make_complaint(db_session, flat, status="Open", linked_to_id=anchor.id)

    response = post_update(staff_client, duplicate, status="In Progress")

    assert response.headers["location"] == f"/staff/complaints?status_changed_id={duplicate.id}"


"""
TEST: status change on a standalone complaint has no reminder
No related complaints means no reminder.
Example: a lone complaint is resolved -> plain redirect to /staff/complaints.
"""
def test_status_change_on_a_standalone_complaint_has_no_reminder(staff_client, db_session, flat):
    lone = make_complaint(db_session, flat, status="Open")

    response = post_update(staff_client, lone, status="Resolved")

    assert response.headers["location"] == "/staff/complaints"


"""
TEST: category only change on a clustered complaint has no reminder
The reminder is only for a REAL status change.
Example: anchor A (with a duplicate) changes category lift -> electrical, status stays
Open -> plain redirect, no reminder.
"""
def test_category_only_change_on_a_clustered_complaint_has_no_reminder(staff_client, db_session, flat):
    anchor = make_complaint(db_session, flat, status="Open", category="lift")
    make_complaint(db_session, flat, status="Open", linked_to_id=anchor.id)

    # Status is resent unchanged ("Open"), only the category moves.
    response = post_update(staff_client, anchor, category="electrical", status="Open")

    assert response.headers["location"] == "/staff/complaints"


BANNER_TEXT = "related report(s) in the same cluster might need a status update too"


"""
TEST: reminder banner shows on the staff page for a clustered complaint
The banner is really visible on the page, not only in the URL.
Example: resolve anchor A, follow the redirect -> the page says
"related report(s) in the same cluster might need a status update too".
"""
def test_reminder_banner_shows_on_the_staff_page_for_a_clustered_complaint(staff_client, db_session, flat):
    # End to end: follow the redirect (default behaviour) and check the page
    # really shows the reminder banner, not just that the URL looks right.
    anchor = make_complaint(db_session, flat, status="Open")
    make_complaint(db_session, flat, status="Open", linked_to_id=anchor.id)

    response = staff_client.post(
        f"/staff/complaints/{anchor.id}/update",
        data={"category": "lift", "status": "Resolved"},
    )

    assert response.status_code == 200
    assert BANNER_TEXT in response.text


"""
TEST: no reminder banner for a standalone complaint
The opposite: no banner when there is nothing related.
Example: resolve a lone complaint, follow the redirect -> the banner text is not on the page.
"""
def test_no_reminder_banner_for_a_standalone_complaint(staff_client, db_session, flat):
    lone = make_complaint(db_session, flat, status="Open")

    response = staff_client.post(
        f"/staff/complaints/{lone.id}/update",
        data={"category": "lift", "status": "Resolved"},
    )

    assert response.status_code == 200
    assert BANNER_TEXT not in response.text

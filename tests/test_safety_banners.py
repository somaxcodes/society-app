"""
=============================================================================
test_safety_banners.py : the red safety-flag banner vs. the amber AI-risk banner
=============================================================================
Two different banners can show on a complaint:
  - RED  "safety-banner"  : complaint.is_safety_flagged is True (a keyword
    in app/safety_check.py matched).
  - AMBER "ai-risk-banner": complaint.urgency == "High" AND
    is_safety_flagged is False (the AI classifier judged it dangerous, but
    no keyword override fired to confirm it).

They are mutually exclusive by definition: is_safety_flagged is either True
or False for a given complaint, so only one of the two conditions above can
ever be true at once. These tests check that both the resident ("My
Complaints") and staff ("Staff Complaints") pages actually render that way.
=============================================================================
"""

from app.models import Complaint

RED_BANNER_TEXT = "SAFETY FLAGGED"
AMBER_BANNER_TEXT = "High priority: this looks serious and needs a quick check."


def make_complaint(db, flat, urgency, safety_flagged):
    complaint = Complaint(
        flat_id=flat.id,
        description="A complaint used for banner testing",
        category="structural",
        urgency=urgency,
        is_safety_flagged=safety_flagged,
        status="Open",
    )
    db.add(complaint)
    db.commit()
    return complaint


"""
TEST: amber banner shows on the resident page for a High, keyword-unconfirmed complaint
Example: urgency High, is_safety_flagged False -> the amber banner text is on
the page, the red banner text is not.
"""
def test_amber_banner_shows_on_resident_page_for_high_unflagged_complaint(
    resident_client, db_session, flat, resident_user
):
    make_complaint(db_session, flat, urgency="High", safety_flagged=False)

    response = resident_client.get("/complaints")

    assert response.status_code == 200
    assert AMBER_BANNER_TEXT in response.text
    assert RED_BANNER_TEXT not in response.text


"""
TEST: red banner shows (not amber) on the resident page once a keyword confirms it
Example: urgency High, is_safety_flagged True -> the red banner text is on
the page, the amber banner text is not.
"""
def test_red_banner_shows_on_resident_page_for_high_flagged_complaint(
    resident_client, db_session, flat, resident_user
):
    make_complaint(db_session, flat, urgency="High", safety_flagged=True)

    response = resident_client.get("/complaints")

    assert response.status_code == 200
    assert RED_BANNER_TEXT in response.text
    assert AMBER_BANNER_TEXT not in response.text


"""
TEST: Medium/Low urgency never gets the amber banner either
Example: urgency Medium, is_safety_flagged False -> neither banner appears.
"""
def test_no_banner_for_non_high_unflagged_complaint(resident_client, db_session, flat, resident_user):
    make_complaint(db_session, flat, urgency="Medium", safety_flagged=False)

    response = resident_client.get("/complaints")

    assert response.status_code == 200
    assert RED_BANNER_TEXT not in response.text
    assert AMBER_BANNER_TEXT not in response.text


"""
TEST: amber banner shows on the staff page for a High, keyword-unconfirmed complaint
Same check as the resident page, but on /staff/complaints.
"""
def test_amber_banner_shows_on_staff_page_for_high_unflagged_complaint(
    staff_client, db_session, flat, staff_user
):
    make_complaint(db_session, flat, urgency="High", safety_flagged=False)

    response = staff_client.get("/staff/complaints")

    assert response.status_code == 200
    assert AMBER_BANNER_TEXT in response.text
    assert RED_BANNER_TEXT not in response.text


"""
TEST: red banner shows (not amber) on the staff page once a keyword confirms it
"""
def test_red_banner_shows_on_staff_page_for_high_flagged_complaint(staff_client, db_session, flat, staff_user):
    make_complaint(db_session, flat, urgency="High", safety_flagged=True)

    response = staff_client.get("/staff/complaints")

    assert response.status_code == 200
    assert RED_BANNER_TEXT in response.text
    assert AMBER_BANNER_TEXT not in response.text


"""
TEST: the two banners are mutually exclusive, explicitly
is_safety_flagged is a plain boolean, so "High + flagged" and
"High + unflagged" can never both be true for the same complaint -- this
checks that directly, independent of which banner text is expected, across
every combination of urgency and flag value.
"""
def test_red_and_amber_banners_never_both_appear_for_one_complaint(
    staff_client, db_session, flat, staff_user
):
    for urgency in ["High", "Medium", "Low"]:
        for safety_flagged in [True, False]:
            db_session.query(Complaint).delete()
            db_session.commit()
            complaint = make_complaint(db_session, flat, urgency=urgency, safety_flagged=safety_flagged)

            # By definition: is_safety_flagged is exactly one of True/False,
            # so these two conditions can never both hold for one complaint.
            shows_red = complaint.is_safety_flagged
            shows_amber = complaint.urgency == "High" and not complaint.is_safety_flagged
            assert not (shows_red and shows_amber)

            response = staff_client.get("/staff/complaints")
            red_shown = RED_BANNER_TEXT in response.text
            amber_shown = AMBER_BANNER_TEXT in response.text
            assert not (red_shown and amber_shown)

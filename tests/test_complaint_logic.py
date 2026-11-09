"""
=============================================================================
test_complaint_logic.py : tests for duplicate complaints ("clusters")
=============================================================================
When several residents report the same problem, the app links them together
into a CLUSTER:

    anchor  <-- duplicate 1        The anchor is the original complaint.
            <-- duplicate 2        Each duplicate has linked_to_id = anchor.id

Rules tested here:
  1. Urgency only ever goes UP across a cluster (Low < Medium < High). The
     whole cluster takes the highest urgency, and nothing is downgraded.
  2. If any complaint in the cluster is safety flagged, the flag spreads to
     the new one.
  3. Unrelated complaints are never touched.
  4. Helper functions build_duplicate_links() and get_cluster_siblings()
     report who is linked to whom (used for the staff page).

These tests use db_session and flat (fixtures from conftest.py), because
complaints are real rows in the (in-memory) test database.
=============================================================================
"""

from app.main import build_duplicate_links, escalate_duplicate_cluster_urgency, get_cluster_siblings
from app.models import Complaint


"""
Helper (not a test, no test_ prefix). Saves one complaint to the database so
each test can set up its scenario in a single line.
"linked_to_id=None" and "safety=False" are default values: if the caller
leaves them out, Python uses these.
"""
def make_complaint(db, flat, urgency, description="Lift making a noise", linked_to_id=None, safety=False):
    complaint = Complaint(
        flat_id=flat.id,
        description=description,
        category="lift",
        urgency=urgency,
        linked_to_id=linked_to_id,  # None means "standalone / this is the anchor"
        is_safety_flagged=safety,
        status="Open",
    )
    db.add(complaint)
    db.commit()
    return complaint


"""
Helper that simulates a resident submitting a new complaint that gets
linked to an existing one (the anchor).
**kwargs collects any extra named arguments into a dictionary called kwargs.
So link_new_complaint(db, flat, anchor, "High", safety=True) puts
{"safety": True} in kwargs, and kwargs.get("safety", False) reads it, using
False if it was not given.
"""
def link_new_complaint(db, flat, anchor, urgency, **kwargs):
    # Mirrors what POST /complaints/new does: build the complaint pointing at
    # the anchor, escalate the cluster, then save it.
    new = Complaint(
        flat_id=flat.id,
        description="Lift noise again",
        category="lift",
        urgency=urgency,
        linked_to_id=anchor.id,
        is_safety_flagged=kwargs.get("safety", False),
        status="Open",
    )
    # The function being tested. It adjusts urgency/safety on the cluster and
    # on "new" BEFORE new is saved.
    escalate_duplicate_cluster_urgency(db, anchor.id, new)
    db.add(new)
    db.commit()
    return new


"""
--- Urgency escalation tests ------------------------------------------------
Each test follows: ARRANGE (set up data) -> ACT (run the code) -> ASSERT.
db_session.refresh(x) reloads x from the database, because the function
changed the row and our in-memory copy would otherwise be out of date.
"""


"""
TEST: high linked to medium escalates both to high
A new High complaint raises the older Medium one.
Example: old complaint "Medium" + new duplicate "High" -> both become High.
"""
def test_high_linked_to_medium_escalates_both_to_high(db_session, flat):
    anchor = make_complaint(db_session, flat, "Medium")

    new = link_new_complaint(db_session, flat, anchor, "High")

    db_session.refresh(anchor)
    assert anchor.urgency == "High"  # the older complaint was raised up
    assert new.urgency == "High"


"""
TEST: low linked to high never downgrades the anchor
Urgency only goes up, never down.
Example: old complaint "High" + new duplicate "Low" -> the old one stays High,
and the new one is raised to High.
"""
def test_low_linked_to_high_never_downgrades_the_anchor(db_session, flat):
    anchor = make_complaint(db_session, flat, "High")

    new = link_new_complaint(db_session, flat, anchor, "Low")

    db_session.refresh(anchor)
    assert anchor.urgency == "High"  # not pulled down
    assert new.urgency == "High"  # pulled up to the cluster's highest


"""
TEST: equal urgency stays unchanged
Nothing changes when both are already equal.
Example: Medium + Medium -> both stay Medium.
"""
def test_equal_urgency_stays_unchanged(db_session, flat):
    anchor = make_complaint(db_session, flat, "Medium")

    new = link_new_complaint(db_session, flat, anchor, "Medium")

    db_session.refresh(anchor)
    # Comparing tuples checks both values in one line.
    assert (anchor.urgency, new.urgency) == ("Medium", "Medium")


"""
TEST: escalation reaches existing duplicates too
The raise reaches everyone in the cluster, not just the first complaint.
Example: anchor Low, earlier duplicate Medium, new complaint High -> all three become High.
"""
def test_escalation_reaches_existing_duplicates_too(db_session, flat):
    # The anchor is Low and an earlier duplicate is Medium. A new High
    # complaint should lift EVERYONE in the cluster, not just the anchor.
    anchor = make_complaint(db_session, flat, "Low")
    earlier_duplicate = make_complaint(db_session, flat, "Medium", linked_to_id=anchor.id)

    new = link_new_complaint(db_session, flat, anchor, "High")

    db_session.refresh(anchor)
    db_session.refresh(earlier_duplicate)
    # A chained == checks that all four values are equal to each other.
    assert anchor.urgency == earlier_duplicate.urgency == new.urgency == "High"


"""
TEST: unrelated complaint is untouched
Complaints about other problems are left alone.
Example: a "Dog barking" complaint (Low) stays Low while the lift cluster is raised to High.
"""
def test_unrelated_complaint_is_untouched(db_session, flat):
    anchor = make_complaint(db_session, flat, "Medium")
    # A different problem (dog barking) with no link to the anchor.
    unrelated = make_complaint(db_session, flat, "Low", description="Dog barking")

    link_new_complaint(db_session, flat, anchor, "High")

    db_session.refresh(unrelated)
    assert unrelated.urgency == "Low"  # must stay Low


"""
TEST: linking to a duplicate walks up to the real anchor
A new complaint always links to the ORIGINAL complaint, never to a middle one.
Example: A <- B (duplicate of A). A new complaint is linked to B -> it ends up
pointing at A instead.
"""
def test_linking_to_a_duplicate_walks_up_to_the_real_anchor(db_session, flat):
    anchor = make_complaint(db_session, flat, "Low")
    middle = make_complaint(db_session, flat, "Low", linked_to_id=anchor.id)

    """
    find_duplicate() should hand back the anchor, but if it ever returned
    a duplicate instead, the new complaint must still point at the root.
    Here we deliberately pass "middle" (a duplicate) to test that safety net.
    """
    new = link_new_complaint(db_session, flat, middle, "High")

    db_session.refresh(anchor)
    assert new.linked_to_id == anchor.id  # points at the root, not at "middle"
    assert anchor.urgency == "High"


# --- Safety flag tests -------------------------------------------------------


"""
TEST: safety flag spreads across the cluster
If one complaint is a safety risk, its duplicates are marked too.
Example: the anchor "gas leak" is safety flagged; a new duplicate worded differently
becomes flagged as well.
"""
def test_safety_flag_spreads_across_the_cluster(db_session, flat):
    anchor = make_complaint(db_session, flat, "High", description="gas leak", safety=True)

    # The new complaint says safety=False, but the anchor is flagged, so the
    # flag should spread to it.
    new = link_new_complaint(db_session, flat, anchor, "High", safety=False)

    assert new.is_safety_flagged is True


"""
TEST: safety flag not added when nobody in cluster has it
No flag appears out of nowhere.
Example: Medium + Medium, none flagged -> still none flagged.
"""
def test_safety_flag_not_added_when_nobody_in_cluster_has_it(db_session, flat):
    # Guards against the opposite bug: flagging everything as a safety issue.
    anchor = make_complaint(db_session, flat, "Medium")

    new = link_new_complaint(db_session, flat, anchor, "Medium")

    db_session.refresh(anchor)
    assert anchor.is_safety_flagged is False
    assert new.is_safety_flagged is False


"""
--- Link-reporting tests ----------------------------------------------------
build_duplicate_links(db, complaint) returns a dictionary with two keys:
  "linked_from"       : the anchor this complaint is a duplicate of (or None)
  "linked_duplicates" : a list of complaints that are duplicates of it
"""


"""
TEST: build duplicate links for the anchor
The original complaint can list the duplicates that point to it.
Example: anchor A with duplicates B and C -> linked_from is None,
linked_duplicates is [B, C].
"""
def test_build_duplicate_links_for_the_anchor(db_session, flat):
    anchor = make_complaint(db_session, flat, "Medium")
    dup_one = make_complaint(db_session, flat, "Medium", linked_to_id=anchor.id)
    dup_two = make_complaint(db_session, flat, "Medium", linked_to_id=anchor.id)

    links = build_duplicate_links(db_session, anchor)

    assert links["linked_from"] is None  # the anchor isn't a duplicate of anything
    # {c.id for c in ...} is a "set comprehension": it builds a set of ids.
    # We compare sets (not lists) because the ORDER of duplicates does not matter.
    assert {c.id for c in links["linked_duplicates"]} == {dup_one.id, dup_two.id}


"""
TEST: build duplicate links for a duplicate
A duplicate can say which complaint it belongs to.
Example: B is a duplicate of A -> linked_from is A, linked_duplicates is empty.
"""
def test_build_duplicate_links_for_a_duplicate(db_session, flat):
    anchor = make_complaint(db_session, flat, "Medium")
    duplicate = make_complaint(db_session, flat, "Medium", linked_to_id=anchor.id)

    links = build_duplicate_links(db_session, duplicate)

    assert links["linked_from"].id == anchor.id  # points back to the anchor
    assert links["linked_duplicates"] == []  # [] is an empty list: nobody links to it


"""
TEST: build duplicate links for a standalone complaint
A complaint with no links has nothing to show.
Example: a lone complaint -> linked_from is None, linked_duplicates is [].
"""
def test_build_duplicate_links_for_a_standalone_complaint(db_session, flat):
    lone = make_complaint(db_session, flat, "Low")

    links = build_duplicate_links(db_session, lone)

    assert links["linked_from"] is None
    assert links["linked_duplicates"] == []


"""
TEST: cluster siblings from a duplicates point of view
"Siblings" means everyone else in the same cluster, not yourself.
Example: cluster A, B, C. Asking from B -> the answer is A and C.
"""
def test_cluster_siblings_from_a_duplicates_point_of_view(db_session, flat):
    # "Siblings" = everyone else in the same cluster, excluding yourself.
    anchor = make_complaint(db_session, flat, "Medium")
    dup_one = make_complaint(db_session, flat, "Medium", linked_to_id=anchor.id)
    dup_two = make_complaint(db_session, flat, "Medium", linked_to_id=anchor.id)

    siblings = get_cluster_siblings(db_session, dup_one)

    assert {c.id for c in siblings} == {anchor.id, dup_two.id}  # not itself

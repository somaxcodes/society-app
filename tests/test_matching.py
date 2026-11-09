"""
=============================================================================
test_matching.py : tests for match_payment() (bank statement reconciliation)
=============================================================================
Staff upload a bank statement. Each row is a payment someone made. The app
must work out WHICH flat paid. match_payment(row, flats, existing_references)
returns three things:
  status  : "matched", "needs_review" or "duplicate"
  flat_id : the matched flat's id, or None if we are not sure
  reason  : a short sentence explaining the decision

It looks at three clues: the flat number in the reference text (like
"T12-0408"), the UPI ID, and the amount. The safe principle: when unsure,
say "needs_review" so a human checks, never guess the wrong flat.

No database is used here, only plain Python objects.
=============================================================================
"""

from types import SimpleNamespace

import pytest

from app.matching import match_payment


def make_flat(id, flat_number, upi_id, amount_due, amount_paid=0):
    """
    Builds a fake flat. A normal helper function (no test_ prefix, so pytest
    will not run it as a test).

    match_payment() only reads these attributes, so no database is needed.
    SimpleNamespace is a tiny built-in Python object where you choose the
    attribute names, so flat.id and flat.bill.amount_due work like on a
    real Flat. "amount_paid=0" is a default value used when none is given.
    """
    return SimpleNamespace(
        id=id,
        flat_number=flat_number,
        upi_id=upi_id,
        bill=SimpleNamespace(amount_due=amount_due, amount_paid=amount_paid),
    )


@pytest.fixture
def flats():
    # A fixture defined in THIS file (so only these tests can use it): a list
    # of three flats shared by all the tests below.
    return [
        make_flat(1, "T07-1203", "neeraj@upi", 7475, amount_paid=7475),  # fully paid
        make_flat(2, "T12-0408", "swati@upi", 6370),
        make_flat(3, "T21-1601", "aamir@upi", 10660, amount_paid=5000),  # 5660 left
    ]


def row(reference, amount, upi_id):
    # Builds one fake bank statement row. A dict (curly brackets) stores
    # "name": value pairs, like a labelled row in a spreadsheet.
    return {"date": "2026-10-01", "amount": amount, "reference": reference, "upi_id": upi_id}


"""
TEST: exact flat and upi match
Best case: the flat number AND the UPI ID both point to the same flat.
Example: reference "MAINT T12-0408 OCT" paid from swati@upi -> matched to flat 2.
"""
def test_exact_flat_and_upi_match(flats):
    """
    The ideal case: flat number AND UPI ID both point at flat 2.
    The third argument, set(), is an empty set: "no references seen before".

    Tuple unpacking: the function returns 3 values and Python splits them
    into the 3 variable names on the left.
    """
    status, flat_id, reason = match_payment(
        row("MAINT T12-0408 OCT", 6370, "swati@upi"), flats, set()
    )

    assert status == "matched"
    assert flat_id == 2
    assert "flat number" in reason and "UPI" in reason


"""
TEST: upi alone is enough to match
No flat number in the text, but the UPI ID belongs to one flat.
Example: reference "REF100234" from aamir@upi -> matched to flat 3.
"""
def test_upi_alone_is_enough_to_match(flats):
    # The reference has no flat number, but the UPI ID is registered to flat 3.
    # "_" is a throwaway name for the value (reason) we do not care about here.
    status, flat_id, _ = match_payment(row("REF100234", 5660, "aamir@upi"), flats, set())

    # Comparing two values at once by putting them in tuples.
    assert (status, flat_id) == ("matched", 3)


"""
TEST: typoed flat number still matches via normalising
Small typing differences in the flat number are ignored.
Example: "T12 0408" (space instead of a dash) still finds flat T12-0408.
"""
def test_typoed_flat_number_still_matches_via_normalising(flats):
    # "T12 0408" has a space instead of a dash. The matcher "normalises" the
    # text (cleans out spaces/dashes/case) so it still finds T12-0408.
    status, flat_id, _ = match_payment(row("T12 0408 maint", 6370, "swati@upi"), flats, set())

    assert (status, flat_id) == ("matched", 2)


"""
TEST: amount only is ambiguous and needs review
An amount on its own is not proof, so a person must check.
Example: someone pays 6370 (what flat 2 owes) but the text and UPI say nothing about
flat 2 -> needs_review, because another person could have paid the same amount.
"""
def test_amount_only_is_ambiguous_and_needs_review(flats):
    """
    6370 is exactly what flat 2 owes, but nothing in the row names a flat.
    Amounts alone are not safe: two flats could owe the same amount. So a
    human must review it.
    """
    status, flat_id, reason = match_payment(
        row("NEFT TRANSFER 00912", 6370, "stranger@upi"), flats, set()
    )

    assert status == "needs_review"
    assert flat_id is None  # "is None" is how Python checks for "nothing"
    assert reason == "Amount matches, but no reliable identifier found"


"""
TEST: nothing matches needs review
No clue matches anything, so a person must check.
Example: "ATM WITHDRAWAL FEE" for 999 from unknown@bank -> needs_review.
"""
def test_nothing_matches_needs_review(flats):
    # No clue matches at all (random reference, unknown UPI, odd amount).
    status, flat_id, reason = match_payment(
        row("ATM WITHDRAWAL FEE", 999, "unknown@bank"), flats, set()
    )

    assert (status, flat_id) == ("needs_review", None)
    assert reason == "No matching flat found"


"""
TEST: duplicate reference is flagged before anything else
The same bank reference is never counted twice, even if it matches perfectly.
Example: "REF100234" was already imported last week; it shows up again -> duplicate.
"""
def test_duplicate_reference_is_flagged_before_anything_else(flats):
    """
    Even a row that would otherwise match perfectly is a duplicate if its
    reference was already processed.
    This protects against counting the same payment twice if the same
    statement is uploaded again. existing_references is the set of
    references we already handled. The curly brackets {"REF100234"} build a
    set. Note this call names the argument (existing_references=...)
    instead of relying on position.
    """
    status, flat_id, reason = match_payment(
        row("REF100234", 6370, "swati@upi"), flats, existing_references={"REF100234"}
    )

    assert status == "duplicate"
    assert flat_id is None
    assert reason == "Reference already processed"


"""
TEST: flat number and upi pointing at different flats needs review
If two clues disagree, do not guess.
Example: the text says T12-0408 but the UPI aamir@upi belongs to another flat -> needs_review.
"""
def test_flat_number_and_upi_pointing_at_different_flats_needs_review(flats):
    # Conflicting clues: the text says flat 2 (T12-0408) but the UPI ID
    # belongs to flat 3 (aamir). Something is off, so don't guess.
    status, flat_id, reason = match_payment(
        row("T12-0408 maintenance", 6370, "aamir@upi"), flats, set()
    )

    assert (status, flat_id) == ("needs_review", None)
    assert reason == "Flat number and UPI ID point to different flats"


"""
TEST: flat number with unregistered upi needs review
The flat number is right, but the UPI ID is unknown.
Example: "T12-0408 maint" paid from cousin@upi (a relative) -> needs_review.
"""
def test_flat_number_with_unregistered_upi_needs_review(flats):
    # Right flat number, but paid from a UPI ID nobody registered (maybe a
    # relative paid on the owner's behalf). A human should confirm.
    status, _, reason = match_payment(row("T12-0408 maint", 6370, "cousin@upi"), flats, set())

    assert status == "needs_review"
    assert "not registered to any flat" in reason


"""
TEST: payment to fully paid flat needs review
A payment for a flat that owes nothing looks odd.
Example: flat 1 already paid all 7475, and another 7475 arrives for it -> needs_review.
"""
def test_payment_to_fully_paid_flat_needs_review(flats):
    # Flat 1 has paid everything already, so a new payment for it is suspicious.
    status, flat_id, reason = match_payment(row("T07-1203 maint", 7475, "neeraj@upi"), flats, set())

    assert (status, flat_id) == ("needs_review", None)
    assert "already fully paid" in reason


"""
TEST: overpayment needs review instead of matching
A payment bigger than what is still owed is not matched automatically.
Example: flat 3 owes 5660 (10660 - 5000 paid), but 10660 arrives -> needs_review.
"""
def test_overpayment_needs_review_instead_of_matching(flats):
    # Flat 3 owes 5660; paying the full 10660 again would overpay it.
    # (10660 due - 5000 already paid = 5660 left, and 10660 is more than that.)
    status, flat_id, reason = match_payment(row("T21-1601 maint", 10660, "aamir@upi"), flats, set())

    assert (status, flat_id) == ("needs_review", None)
    assert "exceeds what is currently owed" in reason

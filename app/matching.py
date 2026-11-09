"""
This file turns one row of a bank statement CSV into a decision about
which flat (if any) it should be matched to. It's pure logic — no
database reads or writes happen here. The caller is responsible for
loading `flats` and `existing_references` from the database first, and
for actually saving a BankPayment row with whatever this function
returns. That split makes match_payment() easy to test on its own,
without a real database.
"""


def _normalize(text: str) -> str:
    """
    "T07-1203" and "t07 1203" and "T071203" should all be treated as the
    same flat number, so before comparing anything we strip out the
    characters that commonly vary (dashes, spaces) and uppercase what's
    left. This is what lets us catch the typo'd rows in the sample CSV
    (e.g. "T07 1203" instead of "T07-1203").
    """
    return text.replace("-", "").replace(" ", "").upper()


def match_payment(row: dict, flats: list, existing_references: set) -> tuple[str, int | None, str]:
    """
    Step 1: duplicate check, before anything else. If we've already
    processed a row with this exact reference, there's no point looking
    for a flat to match it to — it's not a new payment.
    """
    if row["reference"] in existing_references:
        return ("duplicate", None, "Reference already processed")

    normalized_reference = _normalize(row["reference"])

    """
    Step 2: flat_clue — does any flat's number show up inside the
    reference text? We normalize both sides the same way so "T07-1203"
    (the flat number) matches "T07 1203 Maintenance" (the reference).
    """
    flat_clue = None
    for flat in flats:
        if _normalize(flat.flat_number) in normalized_reference:
            flat_clue = flat
            break

    """
    Step 3: upi_clue — does the UPI ID on the payment exactly match a
    flat's registered UPI ID? Unlike flat numbers, UPI IDs aren't
    normalized/fuzzy-matched — they either match exactly or they don't,
    since a typo'd UPI ID could belong to a completely different person.
    """
    upi_clue = None
    for flat in flats:
        if flat.upi_id == row["upi_id"]:
            upi_clue = flat
            break

    """
    Step 4: amount_clue — does the payment amount exactly equal some
    flat's current outstanding balance (amount_due - amount_paid)? We
    only count this if the flat actually owes something (> 0) — a flat
    with nothing outstanding can't be "the" match just because its old
    due amount happens to equal this payment by coincidence.
    """
    amount_clue = None
    for flat in flats:
        outstanding = flat.bill.amount_due - flat.bill.amount_paid
        if outstanding > 0 and row["amount"] == outstanding:
            amount_clue = flat
            break

    """
    Step 5: decide, based on which clues we found and whether they agree.
    flat_clue and upi_clue are the two "reliable" identifiers; amount_clue
    alone is too weak (lots of flats could coincidentally owe the same
    amount), so it's only ever used to explain a "no reliable identifier"
    review case, never to match on its own.
    """
    if flat_clue is not None and upi_clue is not None:
        if flat_clue.id == upi_clue.id:
            """
            Both identifiers agree on the same flat — strongest possible
            signal. Still "tentative" because the fully-paid check below
            can still override this.
            """
            tentative_flat = flat_clue
            match_reason = "flat number in reference and UPI ID both match"
        else:
            """
            Flat number in the reference points to one flat, but the
            money actually came from a UPI ID registered to a different
            flat. That's a genuine conflict — don't guess, send it to a
            human instead of silently picking one.
            """
            return ("needs_review", None, "Flat number and UPI ID point to different flats")
    elif upi_clue is not None:
        # No flat number in the reference text, but the UPI ID is an exact,
        # unambiguous match — that's enough on its own to match.
        tentative_flat = upi_clue
        match_reason = "UPI ID matches"
    elif flat_clue is not None:
        """
        The reference mentions a flat, but the money came from a UPI ID
        we don't recognize. This could be a family member/friend paying
        on the owner's behalf, so we don't reject it outright — but we
        also can't confirm it, so it goes to review instead of auto-matching.
        """
        return (
            "needs_review",
            None,
            "Flat number found in reference, but payer UPI ID is not registered to any flat",
        )
    elif amount_clue is not None:
        # The amount happens to match what some flat owes, but that's a
        # coincidence we can't act on without a name or UPI ID attached.
        return ("needs_review", None, "Amount matches, but no reliable identifier found")
    else:
        # No clue at all — nothing in this row points to any flat.
        return ("needs_review", None, "No matching flat found")

    """
    Step 6: even a tentative match can still be wrong. If the flat we
    landed on has nothing left to pay, this payment isn't settling that
    flat's current bill — it might be a duplicate bank entry, or an
    advance payment for next month, either way it needs a human to look
    at it rather than being silently applied.
    """
    outstanding = tentative_flat.bill.amount_due - tentative_flat.bill.amount_paid
    if outstanding <= 0:
        return (
            "needs_review",
            None,
            "Flat identified, but already fully paid. Possible duplicate or advance payment.",
        )

    """
    The flat does owe something, but if this payment is for more than
    that remaining balance, applying it as-is would overpay the bill —
    that needs a human to confirm rather than being matched silently.
    """
    if row["amount"] > outstanding:
        return (
            "needs_review",
            None,
            "Flat identified, but payment amount exceeds what is currently owed. Possible overpayment, needs confirmation.",
        )

    return ("matched", tentative_flat.id, f"Matched: {match_reason}")


def suggest_flat(row: dict, flats: list):
    """
    For a needs_review row, this gives staff a best guess of "which flat
    did you probably mean?" to display alongside the reason — it reuses
    the same flat-number/UPI clues as match_payment(), but only ever
    returns a guess, never a decision. It does NOT redo the fully-paid or
    overpayment checks, since this isn't deciding whether to apply a
    payment — just helping a human find the right flat faster.
    """
    normalized_reference = _normalize(row["reference"])

    for flat in flats:
        if _normalize(flat.flat_number) in normalized_reference:
            return flat

    for flat in flats:
        if flat.upi_id == row["upi_id"]:
            return flat

    return None

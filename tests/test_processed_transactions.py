"""
=============================================================================
test_processed_transactions.py : tests for GET /staff/processed-transactions
=============================================================================
Matched and duplicate bank payment rows only ever showed up once, as a
count on the one-time upload results page, then were gone. This page is
the parallel of /review-queue: instead of "needs_review" rows, it lists
every row with status "matched" or "duplicate", across every upload ever
done, with counts at the top.
=============================================================================
"""

import re

from tests.test_bank_upload import MIXED_CSV, flats_with_bills, upload  # noqa: F401 (fixture)


def read_counts(response):
    """
    Mirrors test_bank_upload.read_counts: the page prints its counts inside
    <p class="stat-value">, in order: total processed, matched, duplicate.
    """
    numbers = re.findall(r'<p class="stat-value">(\d+)</p>', response.text)
    total, matched, duplicate = (int(n) for n in numbers)
    return {"total": total, "matched": matched, "duplicate": duplicate}


"""
TEST: processed transactions page lists matched and duplicate rows with correct status labels
MIXED_CSV has 2 matched rows, 1 needs_review row, 1 duplicate row. The
matched rows should show "Matched" and the duplicate row should show
"Duplicate".
"""
def test_processed_transactions_lists_matched_and_duplicate_rows_with_status(
    staff_client, flats_with_bills
):
    upload(staff_client, MIXED_CSV)

    response = staff_client.get("/staff/processed-transactions")

    assert response.status_code == 200
    # The matched rows: T12-0408 exact match, T07-1203 exact match.
    assert "MAINT T12-0408 OCT" in response.text
    assert "Maintenance FLAT T07-1203" in response.text
    # The duplicate row (same reference as the T12-0408 match, repeated).
    assert "Duplicate" in response.text
    assert "Matched" in response.text


"""
TEST: processed transactions page shows correct counts at the top
Example: MIXED_CSV -> 2 matched + 1 duplicate = 3 total processed rows.
"""
def test_processed_transactions_shows_correct_counts(staff_client, flats_with_bills):
    upload(staff_client, MIXED_CSV)

    response = staff_client.get("/staff/processed-transactions")

    assert response.status_code == 200
    assert read_counts(response) == {"total": 3, "matched": 2, "duplicate": 1}


"""
TEST: review-queue rows do not appear on the processed transactions page
MIXED_CSV's first row (amount matches, no identifier) is needs_review,
not matched or duplicate -- it belongs only on /review-queue.
"""
def test_review_queue_rows_do_not_appear_on_processed_transactions_page(
    staff_client, flats_with_bills
):
    upload(staff_client, MIXED_CSV)

    response = staff_client.get("/staff/processed-transactions")

    assert response.status_code == 200
    assert "NEFT TRANSFER 00912" not in response.text
    assert "Amount matches, but no reliable identifier found" not in response.text

"""
=============================================================================
test_bank_upload.py : tests for the real POST /bank-upload route
=============================================================================
Staff upload a bank statement CSV. For every row the app decides:
  matched      -> we know which flat paid, so that flat's bill goes up
  needs_review -> not sure, a human must look
  duplicate    -> this reference was already imported before

Unlike test_matching.py (which tests the matching function alone), these
tests go through the WHOLE route: upload a file, read the results page, and
check what ended up in the database.

HOW A FILE IS UPLOADED IN A TEST:
  client.post(url, files={"file": ("name.csv", file_bytes, "text/csv")})
The tuple is (file name, file contents as bytes, content type). The key
"file" must match the parameter name in the route (file: UploadFile).
=============================================================================
"""

import html
import re

import pytest

from app.models import BankPayment, Bill, Flat

CSV_HEADER = "date,amount,reference,upi_id\n"
INVALID_FORMAT_MESSAGE = "Invalid file format"


@pytest.fixture
def flats_with_bills(db_session):
    # Three flats, each with an unpaid bill. Returns a dict so a test can say
    # flats_with_bills["T12-0408"] instead of remembering list positions.
    from datetime import date

    flats = {}
    for flat_number, owner, upi, amount_due in [
        ("T07-1203", "Neeraj", "neeraj@upi", 7475),
        ("T12-0408", "Swati", "swati@upi", 6370),
        ("T21-1601", "Aamir", "aamir@upi", 10660),
    ]:
        flat = Flat(flat_number=flat_number, owner_name=owner, area_sqft=1000, upi_id=upi)
        db_session.add(flat)
        db_session.flush()  # flush gives flat an id without ending the transaction
        db_session.add(Bill(flat_id=flat.id, amount_due=amount_due, amount_paid=0, due_date=date(2026, 10, 10)))
        flats[flat_number] = flat
    db_session.commit()
    return flats


def upload(staff_client, csv_text, filename="statement.csv"):
    # .encode("utf-8") turns the text into bytes, which is what a file is.
    return staff_client.post(
        "/bank-upload",
        files={"file": (filename, csv_text.encode("utf-8"), "text/csv")},
    )


def read_counts(response):
    """
    The results page prints three numbers inside <p class="stat-value">.
    re.findall pulls every match out of the HTML as a list of strings; the
    page always lists them in this order: matched, needs review, duplicate.
    """
    numbers = re.findall(r'<p class="stat-value">(\d+)</p>', response.text)
    matched, needs_review, duplicate = (int(n) for n in numbers)
    return {"matched": matched, "needs_review": needs_review, "duplicate": duplicate}


def paid_amount(db_session, flat):
    bill = db_session.query(Bill).filter(Bill.flat_id == flat.id).first()
    db_session.refresh(bill)  # re-read the latest value from the database
    return bill.amount_paid


"""
One file with all three outcomes. Used by several tests below.

ORDER MATTERS: the amount-only row comes FIRST on purpose. Rows are
processed top to bottom and a matched row immediately raises amount_paid,
so if the T12-0408 payment came first, nobody would owe 6370 any more and
the stranger row's reason would change to "No matching flat found".
"""
MIXED_CSV = (
    CSV_HEADER
    # amount equals what T12-0408 owes but nothing names the flat -> needs_review
    + "2026-10-04,6370,NEFT TRANSFER 00912,stranger@upi\n"
    # exact flat number + UPI match for flat T12-0408 -> matched
    + "2026-10-02,6370,MAINT T12-0408 OCT,swati@upi\n"
    # exact flat number + UPI match for flat T07-1203 -> matched
    + "2026-10-01,7475,Maintenance FLAT T07-1203,neeraj@upi\n"
    # same reference as the T12-0408 row, repeated inside this same file -> duplicate
    + "2026-10-02,6370,MAINT T12-0408 OCT,swati@upi\n"
)


# --- Counts ------------------------------------------------------------------


"""
TEST: upload reports correct matched needs review and duplicate counts
The results page shows the right totals.
Example: the file has 4 rows -> 2 matched, 1 needs review, 1 duplicate.
"""
def test_upload_reports_correct_matched_needs_review_and_duplicate_counts(
    staff_client, flats_with_bills
):
    response = upload(staff_client, MIXED_CSV)

    assert response.status_code == 200
    assert read_counts(response) == {"matched": 2, "needs_review": 1, "duplicate": 1}


"""
TEST: needs review row is listed with its reason
Rows that need review are listed with the reason.
Example: "NEFT TRANSFER 00912" appears with
"Amount matches, but no reliable identifier found".
"""
def test_needs_review_row_is_listed_with_its_reason(staff_client, flats_with_bills):
    response = upload(staff_client, MIXED_CSV)

    assert "NEFT TRANSFER 00912" in response.text
    assert "Amount matches, but no reliable identifier found" in response.text


# --- Database effects --------------------------------------------------------


"""
TEST: matched rows increase amount paid on the right flats
A matched payment really adds to that flat's bill.
Example: 6370 matched to T12-0408 -> that flat's amount_paid goes from 0 to 6370.
"""
def test_matched_rows_increase_amount_paid_on_the_right_flats(
    staff_client, db_session, flats_with_bills
):
    upload(staff_client, MIXED_CSV)

    assert paid_amount(db_session, flats_with_bills["T12-0408"]) == 6370
    assert paid_amount(db_session, flats_with_bills["T07-1203"]) == 7475


"""
TEST: flats with no matched payment are not changed
Money must not leak into the wrong bill.
Example: nobody paid for T21-1601 -> its amount_paid stays 0.
"""
def test_flats_with_no_matched_payment_are_not_changed(staff_client, db_session, flats_with_bills):
    upload(staff_client, MIXED_CSV)

    # Nobody paid for T21-1601; the needs_review and duplicate rows must not
    # leak money into any bill.
    assert paid_amount(db_session, flats_with_bills["T21-1601"]) == 0


"""
TEST: every row is saved with its status
Every row is kept in the database, even duplicates (a record of what happened).
Example: 4 rows uploaded -> 4 saved: 2 matched, 1 needs_review, 1 duplicate.
"""
def test_every_row_is_saved_with_its_status(staff_client, db_session, flats_with_bills):
    upload(staff_client, MIXED_CSV)

    payments = db_session.query(BankPayment).all()
    statuses = sorted(p.status for p in payments)
    # All 4 rows are stored, including the duplicate (kept as an audit trail).
    assert statuses == ["duplicate", "matched", "matched", "needs_review"]

    matched_to = {p.matched_flat_id for p in payments if p.status == "matched"}
    assert matched_to == {
        flats_with_bills["T12-0408"].id,
        flats_with_bills["T07-1203"].id,
    }
    # needs_review and duplicate rows are not tied to any flat.
    assert all(p.matched_flat_id is None for p in payments if p.status != "matched")


# --- Re-uploading the same file ---------------------------------------------


"""
TEST: reuploading the same file marks every row duplicate
Uploading the same file twice does not count anything again.
Example: upload the file, then upload it again -> all 4 rows are duplicates.
"""
def test_reuploading_the_same_file_marks_every_row_duplicate(staff_client, db_session, flats_with_bills):
    upload(staff_client, MIXED_CSV)

    second = upload(staff_client, MIXED_CSV)

    # All 4 rows have references we have already seen.
    assert read_counts(second) == {"matched": 0, "needs_review": 0, "duplicate": 4}


"""
TEST: reuploading does not pay a bill twice
The second upload must not add money again.
Example: T12-0408 paid 6370 the first time -> still 6370 after the second upload, not 12740.
"""
def test_reuploading_does_not_pay_a_bill_twice(staff_client, db_session, flats_with_bills):
    upload(staff_client, MIXED_CSV)
    upload(staff_client, MIXED_CSV)

    # Still the single payment from the first upload, not doubled.
    assert paid_amount(db_session, flats_with_bills["T12-0408"]) == 6370
    assert paid_amount(db_session, flats_with_bills["T07-1203"]) == 7475


"""
TEST: reupload rows are stored as duplicates
Duplicate rows are still saved, with status "duplicate".
Example: 1 duplicate inside the first file + 4 from the second = 5 saved duplicates.
"""
def test_reupload_rows_are_stored_as_duplicates(staff_client, db_session, flats_with_bills):
    upload(staff_client, MIXED_CSV)
    upload(staff_client, MIXED_CSV)

    duplicates = db_session.query(BankPayment).filter(BankPayment.status == "duplicate").count()
    # 1 duplicate from inside the first file + all 4 rows from the second file.
    assert duplicates == 5


# --- Bad files ---------------------------------------------------------------


"""
TEST: wrong columns are rejected
The file must have exactly these columns, in this order: date, amount, reference, upi_id.
Example: a file with only "date,amount,reference" -> "Invalid file format", nothing saved.
"""
@pytest.mark.parametrize(
    "bad_csv",
    [
        "date,amount,reference\n2026-10-01,100,REF1\n",  # a column is missing
        "date,amount,reference,upi_id,extra\n2026-10-01,100,REF1,a@upi,x\n",  # extra column
        "amount,date,reference,upi_id\n100,2026-10-01,REF1,a@upi\n",  # columns in the wrong order
        "name,age\nSwati,30\n",  # a completely different CSV
        "",  # empty file
    ],
    ids=["missing-column", "extra-column", "wrong-order", "different-csv", "empty-file"],
)
def test_wrong_columns_are_rejected(staff_client, db_session, flats_with_bills, bad_csv):
    response = upload(staff_client, bad_csv)

    assert response.status_code == 200
    assert INVALID_FORMAT_MESSAGE in response.text
    assert db_session.query(BankPayment).count() == 0  # nothing was imported


"""
TEST: a non text file is rejected
A file that is not text (like a Word file or an image) is refused.
Example: random binary bytes -> "Invalid file format", nothing saved.
"""
def test_a_non_text_file_is_rejected(staff_client, db_session, flats_with_bills):
    # Bytes that are not valid UTF-8 text at all (like a .docx or an image
    # would contain). b"..." is a bytes literal; \xff and \xfe cannot be decoded.
    response = staff_client.post(
        "/bank-upload",
        files={"file": ("statement.docx", b"\xff\xfe\x00\x01binary\x80\x81", "application/octet-stream")},
    )

    assert response.status_code == 200
    assert INVALID_FORMAT_MESSAGE in response.text
    assert db_session.query(BankPayment).count() == 0


"""
TEST: header only file is valid and imports nothing
A file with only the header line is valid, it just has no rows.
Example: "date,amount,reference,upi_id" and nothing else -> counts are 0, 0, 0.
"""
def test_header_only_file_is_valid_and_imports_nothing(staff_client, db_session, flats_with_bills):
    response = upload(staff_client, CSV_HEADER)

    assert read_counts(response) == {"matched": 0, "needs_review": 0, "duplicate": 0}
    assert db_session.query(BankPayment).count() == 0


# --- Who may upload ----------------------------------------------------------


"""
TEST: resident cannot upload
Only staff may upload bank statements.
Example: a resident uploads a file -> 403 and nothing is saved.
"""
def test_resident_cannot_upload(resident_client, db_session):
    # No flats_with_bills here: resident_client already creates the flat
    # "T07-1203", and flat numbers must be unique.
    response = resident_client.post(
        "/bank-upload",
        files={"file": ("statement.csv", MIXED_CSV.encode("utf-8"), "text/csv")},
    )

    assert response.status_code == 403
    assert db_session.query(BankPayment).count() == 0


"""
TEST: anonymous cannot upload
You must be logged in to upload.
Example: a visitor who is not logged in uploads a file -> 401 and nothing is saved.
"""
def test_anonymous_cannot_upload(client, db_session, flats_with_bills):
    response = client.post(
        "/bank-upload",
        files={"file": ("statement.csv", MIXED_CSV.encode("utf-8"), "text/csv")},
    )

    assert response.status_code == 401
    assert db_session.query(BankPayment).count() == 0


"""
--- Bad rows inside an otherwise well formed file ---------------------------
The header can be perfect while one ROW is broken. The app must answer with a
clean message, never a crash (a 500 error). We reject the WHOLE file and
import nothing: a half imported bank statement is hard to fix afterwards,
because re-uploading the corrected file would mark the good rows "duplicate".
"""

BAD_ROW_ERROR = "Nothing was imported"


def page_text(response):
    """
    The server HTML-escapes quotes (' becomes &#39;). html.unescape turns
    that back into what a person sees in the browser, so we can compare
    against the readable message.
    """
    return html.unescape(response.text)


"""
TEST: a bad row rejects the file with a clean message
Example: the amount is "abc" instead of a number -> the page says
"Line 2: amount 'abc' is not a valid number ... Nothing was imported",
instead of crashing with a 500 error.
"""
@pytest.mark.parametrize(
    "bad_row, expected_text",
    [
        ("2026-10-01,abc,REF1,a@upi", "Line 2: amount 'abc' is not a valid number"),
        ("2026-10-01,,REF1,a@upi", "Line 2: amount '' is not a valid number"),
        ("2026-10-01,nan,REF1,a@upi", "Line 2: amount 'nan' is not a valid number"),
        ("2026-10-01,inf,REF1,a@upi", "Line 2: amount 'inf' is not a valid number"),
        ("01/10/2026,100,REF1,a@upi", "Line 2: date '01/10/2026' is not in YYYY-MM-DD format"),
        ("not-a-date,100,REF1,a@upi", "Line 2: date 'not-a-date' is not in YYYY-MM-DD format"),
        ("2026-10-01,100,REF1", "Line 2: the row is missing a value"),  # too few columns
        ("2026-10-01,100,REF1,a@upi,oops", "Line 2: the row has more values than columns"),
    ],
    ids=["text-amount", "empty-amount", "nan-amount", "inf-amount", "slash-date", "text-date", "short-row", "long-row"],
)
def test_malformed_row_gives_a_clean_error_not_a_crash(
    staff_client, db_session, flats_with_bills, bad_row, expected_text
):
    response = upload(staff_client, CSV_HEADER + bad_row + "\n")

    assert response.status_code == 200
    assert expected_text in page_text(response)
    assert BAD_ROW_ERROR in page_text(response)
    assert db_session.query(BankPayment).count() == 0


"""
TEST: one bad row means NO row is imported
Example: row 1 is a good 6370 payment for T12-0408, row 2 has amount "abc".
The good payment is NOT applied either: T12-0408 stays at 0 paid.
"""
def test_a_bad_row_stops_good_rows_from_being_imported(staff_client, db_session, flats_with_bills):
    csv_text = (
        CSV_HEADER
        + "2026-10-02,6370,MAINT T12-0408 OCT,swati@upi\n"  # a perfectly good row
        + "2026-10-03,abc,REF2,a@upi\n"  # the broken row
    )

    response = upload(staff_client, csv_text)

    assert "Line 3: amount 'abc' is not a valid number" in page_text(response)
    assert db_session.query(BankPayment).count() == 0
    assert paid_amount(db_session, flats_with_bills["T12-0408"]) == 0


"""
TEST: the corrected file can be uploaded after a rejection
Example: upload a file with a bad row (rejected), fix the row, upload again ->
it imports normally. Nothing was marked "duplicate" by the failed attempt.
"""
def test_fixed_file_imports_normally_after_a_rejected_one(staff_client, db_session, flats_with_bills):
    row = "2026-10-02,{amount},MAINT T12-0408 OCT,swati@upi\n"
    upload(staff_client, CSV_HEADER + row.format(amount="6370x"))  # rejected

    second = upload(staff_client, CSV_HEADER + row.format(amount="6370"))  # fixed

    assert read_counts(second) == {"matched": 1, "needs_review": 0, "duplicate": 0}
    assert paid_amount(db_session, flats_with_bills["T12-0408"]) == 6370


"""
TEST: the message reports every bad row, not just the first
Example: lines 2 and 4 are broken -> the message names Line 2 and says
"and 1 more problem row".
"""
def test_error_mentions_how_many_other_rows_are_bad(staff_client, flats_with_bills):
    csv_text = (
        CSV_HEADER
        + "2026-10-01,abc,REF1,a@upi\n"
        + "2026-10-02,100,REF2,a@upi\n"
        + "2026-10-03,xyz,REF3,a@upi\n"
    )

    response = upload(staff_client, csv_text)

    assert "Line 2: amount 'abc' is not a valid number" in page_text(response)
    assert "and 1 more problem row" in page_text(response)

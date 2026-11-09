"""
This script puts some starter data into the database so we have
something real to test with, instead of an empty database.

run_seed(db) does the actual work and is also called automatically by
app/main.py on startup if the database is empty (see Base.metadata there).
You can still run it by hand too:
  python -m app.seed
"""

from datetime import date, datetime, timedelta

from app.auth import hash_password
from app.database import SessionLocal
from app.models import Bill, Complaint, Flat, User
from app.safety_check import check_safety_flag


def run_seed(db):
    """
    Create one staff (help-desk) user. The staff member's real password is
    "staff123" — we never store that as-is, we run it through hash_password()
    first and store only the scrambled result.
    """
    staff = User(
        email="staff@society.com",
        hashed_password=hash_password("staff123"),
        role="staff",
    )
    db.add(staff)  # db.add() stages the row to be saved (doesn't save it yet)

    """
    The 3 sample flats from the problem statement, written as a list of
    dictionaries so we can loop over them below instead of repeating code
    3 times. "amount_paid" and "due_date" are different for each flat because
    the sample data describes 3 different payment situations (fully paid,
    overdue, and partially paid).
    """
    flats_data = [
        {
            "flat_number": "T07-1203",
            "owner_name": "Neeraj Kulkarni",
            "area_sqft": 1150,
            "upi_id": "neeraj.kulkarni@upi",
            "amount_paid": 7475,
            "due_date": date.today(),  # bill due today, fully paid, 0 days overdue
            "resident_email": "neeraj@test.com",
        },
        {
            "flat_number": "T12-0408",
            "owner_name": "Swati Joshi",
            "area_sqft": 980,
            "upi_id": "swati.joshi@upi",
            "amount_paid": 0,
            "due_date": date.today() - timedelta(days=47),  # 47 days overdue, nothing paid
            "resident_email": "swati@test.com",
        },
        {
            "flat_number": "T21-1601",
            "owner_name": "Aamir Shaikh",
            "area_sqft": 1640,
            "upi_id": "aamir.shaikh@upi",
            "amount_paid": 5000,
            "due_date": date.today() - timedelta(days=18),  # 18 days overdue, partially paid
            "resident_email": "aamir@test.com",
        },
        # 4 more flats added for the bank-upload demo CSV: all fully unpaid
        # (amount_paid=0), with a believable mix of overdue days (barely due,
        # to genuinely late) so the staff dashboard's overdue-flats view has
        # some real variety instead of just the 3 original flats.
        {
            "flat_number": "T18-1104",
            "owner_name": "Vikram Singh",
            "area_sqft": 1400,
            "upi_id": "vikram.singh@upi",
            "amount_paid": 0,
            "due_date": date.today() - timedelta(days=5),  # 5 days overdue, barely late
            "resident_email": "vikram@test.com",
        },
        {
            "flat_number": "T03-0501",
            "owner_name": "Priya Nair",
            "area_sqft": 850,
            "upi_id": "priya.nair@upi",
            "amount_paid": 0,
            "due_date": date.today() - timedelta(days=8),  # 8 days overdue, recently due
            "resident_email": "priya@test.com",
        },
        {
            "flat_number": "T15-0902",
            "owner_name": "Rajesh Verma",
            "area_sqft": 1200,
            "upi_id": "rajesh.verma@upi",
            "amount_paid": 0,
            "due_date": date.today() - timedelta(days=32),  # 32 days overdue
            "resident_email": "rajesh@test.com",
        },
        {
            "flat_number": "T09-0210",
            "owner_name": "Fatima Ali",
            "area_sqft": 1050,
            "upi_id": "fatima.ali@upi",
            "amount_paid": 0,
            "due_date": date.today() - timedelta(days=60),  # 60 days overdue, genuinely late
            "resident_email": "fatima@test.com",
        },
    ]

    inserted_count = 0  # just a counter so we can print how many we added at the end
    flats_by_number = {}  # filled in below, used by the sample complaints further down

    # Loop through each flat's data one at a time and create 2 database rows
    # for it: one Flat row, and one Bill row linked to that flat.
    for data in flats_data:
        # Step 1: create the Flat row (the "who lives here, how big is it" info)
        flat = Flat(
            flat_number=data["flat_number"],
            owner_name=data["owner_name"],
            area_sqft=data["area_sqft"],
            upi_id=data["upi_id"],
        )
        db.add(flat)

        """
        db.flush() pushes this flat to the database RIGHT NOW (but doesn't
        fully commit/finish yet). We need to do this because the database
        assigns flat.id automatically, and we need that id below to tell the
        Bill which flat it belongs to. Without flush(), flat.id would still be
        empty (None) at this point.
        """
        db.flush()

        """
        Step 2: create the Bill row for this flat.
        amount_due is calculated, not hardcoded, using the rate given in the
        problem statement: ₹6.50 per sqft per month.
        """
        bill = Bill(
            flat_id=flat.id,  # links this bill to the flat we just created
            amount_due=data["area_sqft"] * 6.5,
            amount_paid=data["amount_paid"],
            due_date=data["due_date"],
        )
        db.add(bill)

        # Step 3: create the resident's login account for this flat, linked
        # via flat_id (same flat.id we just got from the flush() above).
        resident = User(
            email=data["resident_email"],
            hashed_password=hash_password("resident123"),
            role="resident",
            flat_id=flat.id,
        )
        db.add(resident)

        flats_by_number[data["flat_number"]] = flat
        inserted_count += 1

    """
    Sample complaints, so a freshly seeded database (e.g. a fresh Render
    deploy) shows a populated dashboard and complaints list instead of an
    empty one. Category and urgency are hardcoded, plausible values here,
    NOT produced by calling classify_complaint() -- that function hits the
    live Groq API, and seeding runs on every app startup against an empty
    database (including every Render cold start), so depending on a live
    API call there would be slow and unreliable. is_safety_flagged is the
    one exception: check_safety_flag() is pure keyword matching, no API
    call, so it's called directly below instead of being hardcoded, the
    same way the real /complaints/new route uses it.
    """
    complaints_data = [
        {
            "flat_number": "T07-1203",
            "description": "Kitchen tap has been leaking slowly for a few days.",
            "category": "plumbing",
            "urgency": "Medium",
            "status": "Open",
        },
        {
            "flat_number": "T21-1601",
            "description": "Upstairs neighbor's renovation work is noisy during odd hours.",
            "category": "noise",
            "urgency": "Low",
            "status": "In Progress",
        },
        # Duplicate pair: both from the same flat/tower, same category,
        # submitted close together, both Open -- the second one's
        # linked_to_id points at the first (the anchor), same convention the
        # real escalate_duplicate_cluster_urgency() in app/main.py uses
        # (linking always targets the older complaint).
        {
            "flat_number": "T12-0408",
            "description": "The lift in our tower keeps stopping between floors unpredictably.",
            "category": "lift",
            "urgency": "Medium",
            "status": "Open",
            "created_at": datetime.utcnow() - timedelta(hours=3),
        },
        {
            "flat_number": "T12-0408",
            "description": "Lift is behaving the same way again, randomly halting between floors.",
            "category": "lift",
            "urgency": "Medium",
            "status": "Open",
            "created_at": datetime.utcnow() - timedelta(hours=2),
            "link_to_previous": True,
        },
        # Safety-flagged demo: wording chosen so check_safety_flag() really
        # returns True (the gas+smell pair), so the red safety banner is
        # visible on page load without filing a new complaint.
        {
            "flat_number": "T15-0902",
            "description": "I smell gas near the meter room on our floor.",
            "category": "safety",
            "urgency": "High",
            "status": "Open",
        },
        # High urgency but NOT safety-flagged: demonstrates the amber "High
        # priority" banner (urgency High, no safety keyword matched). Wording
        # deliberately avoids every check_safety_flag() keyword.
        {
            "flat_number": "T09-0210",
            "description": (
                "The main electrical panel for our wing seems to be malfunctioning "
                "intermittently, lights flicker across multiple flats."
            ),
            "category": "electrical",
            "urgency": "High",
            "status": "Open",
        },
    ]

    previous_complaint = None
    for data in complaints_data:
        complaint = Complaint(
            flat_id=flats_by_number[data["flat_number"]].id,
            description=data["description"],
            category=data["category"],
            urgency=data["urgency"],
            status=data["status"],
            is_safety_flagged=check_safety_flag(data["description"]),
        )
        if "created_at" in data:
            complaint.created_at = data["created_at"]
        if data.get("link_to_previous"):
            complaint.linked_to_id = previous_complaint.id

        db.add(complaint)
        db.flush()  # assigns complaint.id, needed if the next one links to it
        previous_complaint = complaint

    # Now actually save everything we staged above (1 staff user + 7 flats +
    # 7 bills + 6 complaints) permanently into society.db.
    db.commit()

    print(f"Inserted {inserted_count} flats with bills and resident accounts, plus 1 staff user.")


if __name__ == "__main__":
    # SessionLocal() opens a "conversation" with the database. Nothing we do
    # in run_seed() actually saves to the file until db.commit() runs inside it.
    db = SessionLocal()
    run_seed(db)
    db.close()

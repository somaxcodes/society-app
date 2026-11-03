# This script is a "one-time setup" script. Its only job is to put some
# starter data into the database so we have something real to test with,
# instead of an empty database. Run it once, by itself, like:
#   python -m app.seed

from datetime import date, timedelta

from app.auth import hash_password
from app.database import SessionLocal
from app.models import Bill, Flat, User

# SessionLocal() opens a "conversation" with the database. Nothing we do
# below actually saves to the file until we call db.commit() at the end.
db = SessionLocal()

# Create one staff (help-desk) user. The staff member's real password is
# "staff123" — we never store that as-is, we run it through hash_password()
# first and store only the scrambled result.
staff = User(
    email="staff@society.com",
    hashed_password=hash_password("staff123"),
    role="staff",
)
db.add(staff)  # db.add() stages the row to be saved (doesn't save it yet)

# The 3 sample flats from the problem statement, written as a list of
# dictionaries so we can loop over them below instead of repeating code
# 3 times. "amount_paid" and "due_date" are different for each flat because
# the sample data describes 3 different payment situations (fully paid,
# overdue, and partially paid).
flats_data = [
    {
        "flat_number": "T07-1203",
        "owner_name": "Neeraj Kulkarni",
        "area_sqft": 1150,
        "upi_id": "neeraj.kulkarni@upi",
        "amount_paid": 7475,
        "due_date": date.today(),  # bill due today, fully paid, 0 days overdue
    },
    {
        "flat_number": "T12-0408",
        "owner_name": "Swati Joshi",
        "area_sqft": 980,
        "upi_id": "swati.joshi@upi",
        "amount_paid": 0,
        "due_date": date.today() - timedelta(days=47),  # 47 days overdue, nothing paid
    },
    {
        "flat_number": "T21-1601",
        "owner_name": "Aamir Shaikh",
        "area_sqft": 1640,
        "upi_id": "aamir.shaikh@upi",
        "amount_paid": 5000,
        "due_date": date.today() - timedelta(days=18),  # 18 days overdue, partially paid
    },
]

inserted_count = 0  # just a counter so we can print how many we added at the end

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

    # db.flush() pushes this flat to the database RIGHT NOW (but doesn't
    # fully commit/finish yet). We need to do this because the database
    # assigns flat.id automatically, and we need that id below to tell the
    # Bill which flat it belongs to. Without flush(), flat.id would still be
    # empty (None) at this point.
    db.flush()

    # Step 2: create the Bill row for this flat.
    # amount_due is calculated, not hardcoded, using the rate given in the
    # problem statement: ₹6.50 per sqft per month.
    bill = Bill(
        flat_id=flat.id,  # links this bill to the flat we just created
        amount_due=data["area_sqft"] * 6.5,
        amount_paid=data["amount_paid"],
        due_date=data["due_date"],
    )
    db.add(bill)
    inserted_count += 1

# Now actually save everything we staged above (1 staff user + 3 flats +
# 3 bills) permanently into society.db.
db.commit()

# Close the conversation with the database — good practice once we're done.
db.close()

print(f"Inserted {inserted_count} flats with bills, plus 1 staff user.")

from datetime import date, timedelta

from app.database import SessionLocal
from app.models import Bill, Flat, User

db = SessionLocal()

staff = User(
    email="staff@society.com",
    hashed_password="placeholder",
    role="staff",
)
db.add(staff)

flats_data = [
    {
        "flat_number": "T07-1203",
        "owner_name": "Neeraj Kulkarni",
        "area_sqft": 1150,
        "upi_id": "neeraj.kulkarni@upi",
        "amount_paid": 7475,
        "due_date": date.today(),
    },
    {
        "flat_number": "T12-0408",
        "owner_name": "Swati Joshi",
        "area_sqft": 980,
        "upi_id": "swati.joshi@upi",
        "amount_paid": 0,
        "due_date": date.today() - timedelta(days=47),
    },
    {
        "flat_number": "T21-1601",
        "owner_name": "Aamir Shaikh",
        "area_sqft": 1640,
        "upi_id": "aamir.shaikh@upi",
        "amount_paid": 5000,
        "due_date": date.today() - timedelta(days=18),
    },
]

inserted_count = 0

for data in flats_data:
    flat = Flat(
        flat_number=data["flat_number"],
        owner_name=data["owner_name"],
        area_sqft=data["area_sqft"],
        upi_id=data["upi_id"],
    )
    db.add(flat)
    db.flush()  # so flat.id is assigned before we create its bill

    bill = Bill(
        flat_id=flat.id,
        amount_due=data["area_sqft"] * 6.5,
        amount_paid=data["amount_paid"],
        due_date=data["due_date"],
    )
    db.add(bill)
    inserted_count += 1

db.commit()
db.close()

print(f"Inserted {inserted_count} flats with bills, plus 1 staff user.")

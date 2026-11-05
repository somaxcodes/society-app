# A plain, read-the-output-yourself script for trying out match_payment()
# against the real database and the sample bank statement. Not a pytest
# test — just run it directly:
#   python -m test_matching_manual

import csv

from app.database import SessionLocal
from app.matching import match_payment
from app.models import Flat

CSV_PATH = "sample_data/bank_statement_sample.csv"


def main():
    db = SessionLocal()

    # Load every flat, each with its bill attached as `.bill` (singular) —
    # that's the shape match_payment() expects (see app/matching.py). Every
    # flat in our current seed data has exactly one bill, so bills[0] is
    # always "the" bill; this would need revisiting once flats can have
    # more than one (e.g. a new bill each month).
    flats = db.query(Flat).all()
    for flat in flats:
        flat.bill = flat.bills[0]

    # match_payment() needs to know which references it's already seen so
    # it can flag duplicates. We start empty and add each reference as we
    # go, exactly the way a real import loop would.
    existing_references = set()

    with open(CSV_PATH, newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            # The CSV gives us strings for every column, but match_payment()
            # compares row["amount"] against bill math done in floats, so it
            # has to be converted before we call it.
            row["amount"] = float(row["amount"])

            status, matched_flat_id, reason = match_payment(row, flats, existing_references)

            print(f"reference={row['reference']!r} amount={row['amount']} "
                  f"-> status={status}, matched_flat_id={matched_flat_id}, reason={reason!r}")

            # Only add the reference to the seen-set after processing it —
            # this is what lets the *second* occurrence of a duplicate
            # reference (further down the CSV) get flagged, while the first
            # occurrence still gets matched normally.
            existing_references.add(row["reference"])

    db.close()


if __name__ == "__main__":
    main()

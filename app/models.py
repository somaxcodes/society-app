# This file defines our database tables as Python classes. Each class
# below becomes one table in society.db (because it inherits Base — see
# app/database.py for what Base does). Each attribute inside the class
# (like "email: Mapped[str]") becomes one column in that table.

from datetime import date, datetime

from sqlalchemy import CheckConstraint, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


# Table: users
# One row per login account (resident or staff). Not linked to a specific
# flat yet — that's a gap we noted to come back to when we build login.
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)  # auto-numbered unique id
    email: Mapped[str] = mapped_column(unique=True)  # unique=True: no two users can share an email
    hashed_password: Mapped[str]  # NEVER store the real password, only a hashed (scrambled) version
    role: Mapped[str]  # "resident" or "staff" — decides what the user is allowed to do

    # int | None means this column can be NULL. It's nullable because staff
    # users aren't tied to any flat — only residents are.
    flat_id: Mapped[int | None] = mapped_column(ForeignKey("flats.id"), nullable=True)


# Table: flats
# One row per flat in the township (2,400 of them in the real scenario,
# just 3 for now from our sample data).
class Flat(Base):
    __tablename__ = "flats"

    id: Mapped[int] = mapped_column(primary_key=True)
    flat_number: Mapped[str] = mapped_column(unique=True)  # e.g. "T07-1203"
    owner_name: Mapped[str]
    area_sqft: Mapped[float]  # used to calculate the monthly bill (area * rate)
    upi_id: Mapped[str]  # used later to help match bank payments to this flat

    # This line does NOT create a column in the table. It's a shortcut so
    # that in Python, if you have a `flat` object, you can write
    # `flat.bills` to instantly get the list of all Bill rows for this flat,
    # without writing a database query yourself. back_populates="flat"
    # links it to the matching line in the Bill class below.
    bills: Mapped[list["Bill"]] = relationship(back_populates="flat")


# Table: bills
# One row per maintenance bill (normally one per flat per month).
class Bill(Base):
    __tablename__ = "bills"

    id: Mapped[int] = mapped_column(primary_key=True)

    # ForeignKey("flats.id") means: this column must always hold a real id
    # that exists in the flats table. This is how we say "this bill belongs
    # to that flat" at the database level.
    flat_id: Mapped[int] = mapped_column(ForeignKey("flats.id"))

    amount_due: Mapped[float]  # how much this bill is for
    amount_paid: Mapped[float] = mapped_column(default=0)  # how much has actually been paid so far (default 0 = unpaid)
    due_date: Mapped[date]  # when this bill was/is due — used to calculate "days overdue"

    # The reverse shortcut of Flat.bills above: lets us write `bill.flat`
    # in Python to get the Flat this bill belongs to, instead of a query.
    flat: Mapped["Flat"] = relationship(back_populates="bills")


# Table: bank_payments
# One row per line in a bank statement CSV we import, before and after we
# try to match it to a flat. The matching logic itself lives elsewhere —
# this table just holds the raw row plus whatever that logic decided.
class BankPayment(Base):
    __tablename__ = "bank_payments"

    id: Mapped[int] = mapped_column(primary_key=True)

    # These four columns are the raw statement row, copied as-is from the
    # bank CSV (see sample_data/bank_statement_sample.csv).
    date: Mapped[date]
    amount: Mapped[float]
    # Duplicate detection happens in app code (app/matching.py checks a row's
    # reference against every reference already in this table), not via a
    # DB constraint — a duplicate row still needs to be stored here (with
    # status="duplicate") as an audit trail, so reference can't be unique.
    # index=True keeps that "does this reference already exist" check fast.
    reference: Mapped[str] = mapped_column(index=True)
    upi_id: Mapped[str]

    # Which flat the matching logic decided this payment belongs to.
    # Nullable because a "needs_review" or "duplicate" row may never get
    # matched to a flat at all.
    matched_flat_id: Mapped[int | None] = mapped_column(ForeignKey("flats.id"), nullable=True)

    # "matched", "needs_review", or "duplicate" — set by the matching logic.
    # The CheckConstraint below stops any other value from ever being saved,
    # so a typo in the matching code fails loudly instead of writing a
    # status that the rest of the app silently doesn't recognize.
    status: Mapped[str]

    # Human-readable explanation of why this row got that status, e.g.
    # "exact flat number and UPI match" or "duplicate of row 7 (same reference)".
    reason: Mapped[str]

    __table_args__ = (
        CheckConstraint("status IN ('matched', 'needs_review', 'duplicate')", name="ck_bank_payments_status"),
    )


# Table: complaints
# One row per resident complaint. The classification logic (category,
# urgency, duplicate detection via linked_to_id) lives elsewhere — this
# table just holds the complaint plus whatever that logic decided.
class Complaint(Base):
    __tablename__ = "complaints"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Which flat this complaint was raised from.
    flat_id: Mapped[int] = mapped_column(ForeignKey("flats.id"))

    description: Mapped[str]  # the resident's own free-text description of the issue

    # Set by the (not-yet-written) classification logic.
    category: Mapped[str]
    urgency: Mapped[str]

    # "Open", "In Progress", or "Resolved" — defaults to "Open" since every
    # complaint starts out unhandled.
    status: Mapped[str] = mapped_column(default="Open")

    # Points at another Complaint's id when this one is a duplicate of an
    # existing, already-open complaint (e.g. 5 residents reporting the same
    # lift outage). Nullable because most complaints aren't duplicates.
    linked_to_id: Mapped[int | None] = mapped_column(ForeignKey("complaints.id"), nullable=True)

    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    # Set by the classification logic when a complaint's description
    # suggests an immediate safety risk (e.g. gas leak, fire, exposed
    # wiring) — lets staff surface these ahead of everything else,
    # regardless of urgency/category.
    is_safety_flagged: Mapped[bool] = mapped_column(default=False)

    # When this complaint most recently became "Resolved". Nullable: None
    # for a complaint that's never been resolved, or that was resolved and
    # then reopened (see the staff update route for exactly when this gets
    # set vs. cleared). Used to calculate average resolution time.
    resolved_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        CheckConstraint(
            "category IN ('plumbing', 'electrical', 'lift', 'security', 'cleaning', "
            "'safety', 'structural', 'parking', 'noise', 'other')",
            name="ck_complaints_category",
        ),
        CheckConstraint("urgency IN ('Low', 'Medium', 'High')", name="ck_complaints_urgency"),
        CheckConstraint("status IN ('Open', 'In Progress', 'Resolved')", name="ck_complaints_status"),
    )

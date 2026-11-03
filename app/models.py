# This file defines our database tables as Python classes. Each class
# below becomes one table in society.db (because it inherits Base — see
# app/database.py for what Base does). Each attribute inside the class
# (like "email: Mapped[str]") becomes one column in that table.

from datetime import date

from sqlalchemy import ForeignKey
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

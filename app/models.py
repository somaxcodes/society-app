from datetime import date

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(unique=True)
    hashed_password: Mapped[str]
    role: Mapped[str]  # "resident" or "staff"


class Flat(Base):
    __tablename__ = "flats"

    id: Mapped[int] = mapped_column(primary_key=True)
    flat_number: Mapped[str] = mapped_column(unique=True)
    owner_name: Mapped[str]
    area_sqft: Mapped[float]
    upi_id: Mapped[str]

    bills: Mapped[list["Bill"]] = relationship(back_populates="flat")


class Bill(Base):
    __tablename__ = "bills"

    id: Mapped[int] = mapped_column(primary_key=True)
    flat_id: Mapped[int] = mapped_column(ForeignKey("flats.id"))
    amount_due: Mapped[float]
    amount_paid: Mapped[float] = mapped_column(default=0)
    due_date: Mapped[date]

    flat: Mapped["Flat"] = relationship(back_populates="bills")

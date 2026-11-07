# This is the entry point of the whole app — the file that actually
# starts the FastAPI web server and defines the web pages/routes.

import csv
import io
import os
from datetime import date, datetime

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app.auth import verify_password
from app.classification import classify_complaint, find_duplicate
from app.database import Base, SessionLocal, engine, get_db
from app.matching import match_payment, suggest_flat

from app.models import BankPayment, Bill, Complaint, Flat, User

# load_dotenv() reads the .env file in the project root and makes its
# values available via os.getenv(), as if they were set in the environment.
# .env is in .gitignore on purpose: it holds secrets that shouldn't be
# committed to git. This has to run before anything below reads an env var.
load_dotenv()

# This line runs once, when the app starts up. It checks society.db: for
# every table that doesn't exist yet (users, flats, bills), it creates it.
# If the tables already exist, it does nothing to them (it won't update
# a table even if we've changed the model since — more on that if we hit it).
Base.metadata.create_all(bind=engine)

# If the database is brand new (no flats yet), fill it with sample data so
# there's something to log in and test with. This only ever runs once per
# database file — once seeded, Flat.count() is no longer 0, so later app
# startups skip this entirely.
seed_check_db = SessionLocal()
if seed_check_db.query(Flat).count() == 0:
    from app.seed import run_seed

    run_seed(seed_check_db)
seed_check_db.close()

# This is the actual FastAPI application object. Everything below this
# line is defining what the app can do.
app = FastAPI()

# SessionMiddleware lets us store small bits of data (like "this browser is
# logged in as user X") in a signed cookie on the user's browser, between
# requests. "Signed" means the cookie's contents can't be tampered with
# without knowing secret_key — that's why secret_key comes from .env instead
# of being hardcoded here.
secret_key = os.getenv("SECRET_KEY")
if not secret_key:
    # Failing loudly here beats the alternative: SessionMiddleware silently
    # accepting None/"" and signing every session cookie with a key anyone
    # could guess, which would let someone forge a logged-in session.
    raise RuntimeError("SECRET_KEY not set in .env")

app.add_middleware(SessionMiddleware, secret_key=secret_key)

# Jinja2Templates lets us render .html files from app/templates/ as actual
# web pages, instead of just returning JSON like the "/" route below does.
templates = Jinja2Templates(directory="app/templates")


# @app.get("/") means: when someone visits the home page ("/") with a
# normal browser visit (a GET request), run the function right below it.
@app.get("/")
def home(request: Request):
    role = request.session.get("role")

    if role == "resident":
        return RedirectResponse(url="/bills")
    if role == "staff":
        return RedirectResponse(url="/staff/dashboard")

    return RedirectResponse(url="/login")


@app.get("/login")
def login_page(request: Request):
    # TemplateResponse needs "request" — Starlette uses it internally (e.g.
    # for building URLs), so it's always the first argument passed in.
    return templates.TemplateResponse(request, "login.html")


@app.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    # Form(...) means "read this field from the submitted form data" —
    # that's what login.html's <input name="email"> / name="password">
    # end up as. Depends(get_db) hands this route its own database session,
    # same as every other route that needs to query the database.
    user = db.query(User).filter(User.email == email).first()

    # We check "user is None" and "password doesn't match" together, and
    # give the exact same error message either way. If we said "no account
    # with that email" vs "wrong password" separately, anyone could use
    # that to figure out which emails have accounts — a small but real
    # privacy leak.
    if user is None or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Invalid email or password"},
        )

    # request.session is the signed cookie SessionMiddleware set up. Writing
    # to it here is what makes the browser "stay logged in" on later
    # requests — every request carries the cookie back, and we can read
    # request.session["user_id"] to know who's asking.
    request.session["user_id"] = user.id
    request.session["role"] = user.role

    # RedirectResponse sends the browser to a new URL instead of returning
    # a page directly. Both roles go to "/" for now — once we build
    # separate resident/staff pages, this is where we'd branch on role.
    return RedirectResponse(url="/", status_code=303)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    # A FastAPI dependency can't redirect the browser to the login page —
    # it can only let the route run or stop it by raising an exception.
    # 401 Unauthorized is the standard status for "you need to log in".
    user_id = request.session.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Not logged in")

    # The session only stores the id, not the whole user, so every request
    # we look the current row up fresh — this also covers the case where
    # the user was deleted after they logged in.
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=401, detail="Not logged in")

    return user


def require_role(role: str):
    # require_role("staff") doesn't check anything itself — it returns a
    # new function (dependency) that does. That's what lets us write
    # Depends(require_role("staff")) on a route: FastAPI calls that inner
    # function per-request, and it closes over "role" from here.
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role != role:
            raise HTTPException(status_code=403, detail="Forbidden")
        return user

    return dependency


@app.get("/logout")
def logout(request: Request):
    # .clear() wipes everything we stored in the session cookie (user_id,
    # role), so the next request looks "logged out" again.
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@app.get("/staff-only")
def staff_only(user: User = Depends(require_role("staff"))):
    return {"message": "you are staff"}


@app.get("/me")
def me(user: User = Depends(get_current_user)):
    return {"email": user.email, "role": user.role}


@app.get("/bills")
def bills_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Staff don't have a flat_id, so there's nothing to look up for them.
    # We show a plain message instead of letting the query below crash on
    # flat_id=None (which would just find no flat and still need handling).
    if user.flat_id is None:
        return templates.TemplateResponse(
            request,
            "bills.html",
            {"no_flat": True},
        )

    flat = db.query(Flat).filter(Flat.id == user.flat_id).first()
    # A flat always has exactly one bill in our current sample data, so we
    # grab the first (and only) one. first() on a list, not a list, is a
    # SQLAlchemy stand-in for "get one row or None".
    bill = db.query(Bill).filter(Bill.flat_id == flat.id).first()

    outstanding = bill.amount_due - bill.amount_paid
    # max(0, ...) means "never negative" — if the bill isn't overdue yet,
    # due_date is in the future, and (today - due_date) would be negative.
    days_overdue = max(0, (date.today() - bill.due_date).days)

    return templates.TemplateResponse(
        request,
        "bills.html",
        {
            "flat": flat,
            "bill": bill,
            "outstanding": outstanding,
            "days_overdue": days_overdue,
        },
    )


@app.get("/staff/dashboard")
def staff_dashboard(
    request: Request,
    user: User = Depends(require_role("staff")),
    db: Session = Depends(get_db),
):
    flats = db.query(Flat).all()

    total_collections = 0
    overdue_flats = []

    for flat in flats:
        for bill in flat.bills:
            total_collections += bill.amount_paid

            is_overdue = bill.due_date < date.today() and bill.amount_paid < bill.amount_due
            if is_overdue:
                overdue_flats.append(
                    {
                        "flat_number": flat.flat_number,
                        "owner_name": flat.owner_name,
                        "outstanding": bill.amount_due - bill.amount_paid,
                        "days_overdue": (date.today() - bill.due_date).days,
                    }
                )

    return templates.TemplateResponse(
        request,
        "staff_dashboard.html",
        {
            "total_collections": total_collections,
            "overdue_flats": overdue_flats,
        },
    )


@app.get("/bank-upload")
def bank_upload_page(request: Request, user: User = Depends(require_role("staff"))):
    return templates.TemplateResponse(request, "bank_upload.html")


@app.post("/bank-upload")
def bank_upload(
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(require_role("staff")),
    db: Session = Depends(get_db),
):
    # file.file is the plain Python file object FastAPI stores the upload
    # in. Reading from it directly (instead of awaiting file.read()) is
    # what lets this stay a regular sync "def" route, like every other
    # route in this file.
    #
    # A non-CSV upload (e.g. a .docx or corrupted file) can fail in ways
    # that are hard to enumerate up front — wrong encoding, binary bytes
    # that choke decode(), etc. Catching broadly here and reporting the
    # same "invalid format" message is simpler than guessing every way
    # reading an arbitrary file can fail, and it's still what the user
    # needs to know either way: "this isn't the file we expected."
    try:
        text = file.file.read().decode("utf-8")
        reader = csv.DictReader(io.StringIO(text))
        fieldnames = reader.fieldnames
    except Exception:
        return templates.TemplateResponse(
            request,
            "bank_upload.html",
            {"error": "Invalid file format — expected columns: date, amount, reference, upi_id"},
        )

    expected_columns = ["date", "amount", "reference", "upi_id"]
    if fieldnames != expected_columns:
        return templates.TemplateResponse(
            request,
            "bank_upload.html",
            {"error": "Invalid file format — expected columns: date, amount, reference, upi_id"},
        )

    # Every flat that has a bill, with that bill attached as `.bill`
    # (singular) — that's the shape match_payment() expects (see
    # app/matching.py). A flat with no bill at all can't be matched
    # against, so it's left out of the candidate list entirely.
    flats = [flat for flat in db.query(Flat).all() if flat.bills]
    for flat in flats:
        flat.bill = flat.bills[0]

    # Duplicate detection needs to see every reference ever imported, not
    # just this file's rows, so we seed it from the whole bank_payments
    # table before processing a single row of the new upload.
    existing_references = {row.reference for row in db.query(BankPayment.reference).all()}

    counts = {"matched": 0, "needs_review": 0, "duplicate": 0}
    needs_review_rows = []

    for row in reader:
        # Every value from csv.DictReader is a string — match_payment()
        # does real arithmetic on the amount, so it has to become a float
        # before we call it.
        row["amount"] = float(row["amount"])

        status, matched_flat_id, reason = match_payment(row, flats, existing_references)

        db.add(
            BankPayment(
                date=datetime.strptime(row["date"], "%Y-%m-%d").date(),
                amount=row["amount"],
                reference=row["reference"],
                upi_id=row["upi_id"],
                matched_flat_id=matched_flat_id,
                status=status,
                reason=reason,
            )
        )

        if status == "matched":
            matched_flat = next(flat for flat in flats if flat.id == matched_flat_id)
            matched_flat.bill.amount_paid += row["amount"]

        if status == "needs_review":
            needs_review_rows.append(
                {
                    "date": row["date"],
                    "amount": row["amount"],
                    "reference": row["reference"],
                    "upi_id": row["upi_id"],
                    "reason": reason,
                }
            )

        counts[status] += 1

        # Only added now, after this row has been checked against it — so
        # a reference repeated twice within this same file still gets
        # caught as a duplicate on its second occurrence.
        existing_references.add(row["reference"])

    db.commit()

    return templates.TemplateResponse(
        request,
        "bank_upload_results.html",
        {
            "counts": counts,
            "needs_review_rows": needs_review_rows,
        },
    )


@app.get("/review-queue")
def review_queue(
    request: Request,
    user: User = Depends(require_role("staff")),
    db: Session = Depends(get_db),
):
    # Every row still waiting on a human, across every upload ever done —
    # not just the one that was just processed.
    needs_review = db.query(BankPayment).filter(BankPayment.status == "needs_review").all()

    flats = db.query(Flat).all()

    rows = []
    for payment in needs_review:
        # suggest_flat() is a best guess for display only — it does not
        # change the payment's stored status or reason, and it's recomputed
        # fresh each time this page loads so it reflects the current flats.
        suggested_flat = suggest_flat(
            {"reference": payment.reference, "upi_id": payment.upi_id}, flats
        )
        rows.append(
            {
                "date": payment.date,
                "amount": payment.amount,
                "reference": payment.reference,
                "upi_id": payment.upi_id,
                "reason": payment.reason,
                "suggested_flat_number": suggested_flat.flat_number if suggested_flat else None,
                "suggested_owner_name": suggested_flat.owner_name if suggested_flat else None,
            }
        )

    return templates.TemplateResponse(request, "review_queue.html", {"rows": rows})


@app.post("/bills/pay")
def pay_bill(
    request: Request,
    amount: float = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.flat_id is None:
        return templates.TemplateResponse(
            request,
            "bills.html",
            {"no_flat": True},
        )

    flat = db.query(Flat).filter(Flat.id == user.flat_id).first()
    bill = db.query(Bill).filter(Bill.flat_id == flat.id).first()
    outstanding = bill.amount_due - bill.amount_paid
    days_overdue = max(0, (date.today() - bill.due_date).days)

    # Re-render the same page with an error instead of applying a payment
    # that doesn't make sense (nothing paid, or paying more than is owed).
    if amount <= 0 or amount > outstanding:
        return templates.TemplateResponse(
            request,
            "bills.html",
            {
                "flat": flat,
                "bill": bill,
                "outstanding": outstanding,
                "days_overdue": days_overdue,
                "error": "Enter an amount greater than 0 and no more than the outstanding balance",
            },
        )

    bill.amount_paid += amount
    db.commit()

    return RedirectResponse(url="/bills", status_code=303)


@app.get("/complaints/new")
def complaint_new_page(request: Request, user: User = Depends(require_role("resident"))):
    return templates.TemplateResponse(request, "complaint_new.html")


@app.post("/complaints/new")
def complaint_new(
    request: Request,
    # Form(...) treats a submitted-but-empty value as "missing" and rejects
    # it with a raw 422 before this function body ever runs — Form(default="")
    # lets an empty string through so our own validation below can give a
    # friendly re-rendered error instead.
    description: str = Form(default=""),
    user: User = Depends(require_role("resident")),
    db: Session = Depends(get_db),
):
    description = description.strip()

    if not description or len(description) > 1000:
        return templates.TemplateResponse(
            request,
            "complaint_new.html",
            {"error": "Please enter a description between 1 and 1000 characters"},
        )

    flat = db.query(Flat).filter(Flat.id == user.flat_id).first()

    classification = classify_complaint(description)
    linked_to_id = find_duplicate(db, flat, classification["category"], description)

    complaint = Complaint(
        flat_id=flat.id,
        description=description,
        category=classification["category"],
        urgency=classification["urgency"],
        is_safety_flagged=classification["is_safety_flagged"],
        linked_to_id=linked_to_id,
        status="Open",
    )
    db.add(complaint)
    db.commit()

    return RedirectResponse(url="/complaints", status_code=303)


@app.get("/complaints")
def complaint_list(
    request: Request,
    user: User = Depends(require_role("resident")),
    db: Session = Depends(get_db),
):
    complaints = (
        db.query(Complaint)
        .filter(Complaint.flat_id == user.flat_id)
        .order_by(Complaint.created_at.desc())
        .all()
    )

    rows = []
    for complaint in complaints:
        # The complaint this one was linked to as a duplicate (if any) —
        # looked up fresh each time, by id, rather than relying on a
        # relationship, since linked_to_id can point at a complaint
        # belonging to a different flat.
        linked_from = None
        if complaint.linked_to_id is not None:
            linked_from = db.query(Complaint).filter(Complaint.id == complaint.linked_to_id).first()

        # Other complaints that point back at THIS one — i.e. this
        # complaint is the "original" and these are its duplicates.
        linked_duplicates = db.query(Complaint).filter(Complaint.linked_to_id == complaint.id).all()

        rows.append(
            {
                "complaint": complaint,
                "linked_from": linked_from,
                "linked_duplicates": linked_duplicates,
            }
        )

    return templates.TemplateResponse(request, "complaint_list.html", {"rows": rows})


# These must stay in sync with the CheckConstraints on Complaint in
# app/models.py — they're the single source of truth for what's valid;
# these lists are just this file's own copy to build checkboxes/dropdowns
# and to validate the staff update form against.
ALL_CATEGORIES = [
    "plumbing", "electrical", "lift", "security", "cleaning",
    "safety", "structural", "parking", "noise", "other",
]
ALL_STATUSES = ["Open", "In Progress", "Resolved"]

# Lower number = higher priority. Used only for the "urgency" sort below.
URGENCY_RANK = {"High": 0, "Medium": 1, "Low": 2}


@app.get("/staff/complaints")
def staff_complaints_page(
    request: Request,
    sort: str = "urgency",
    category: list[str] = Query(default=[]),
    status: list[str] = Query(default=[]),
    user: User = Depends(require_role("staff")),
    db: Session = Depends(get_db),
):
    query = db.query(Complaint)

    # No category/status checkboxes ticked means "show all" — only filter
    # when the staff member actually chose something.
    if category:
        query = query.filter(Complaint.category.in_(category))
    if status:
        query = query.filter(Complaint.status.in_(status))

    complaints = query.all()

    if sort == "latest":
        complaints.sort(key=lambda complaint: complaint.created_at, reverse=True)
    else:
        # Default: urgency tier first (High, Medium, Low), newest first
        # within each tier. Sorting by a tuple does both in one pass —
        # Python sorts tuples left-to-right, so rank is the primary key
        # and the negative timestamp (newest = largest = sorts first) is
        # the tiebreaker.
        complaints.sort(
            key=lambda complaint: (
                URGENCY_RANK.get(complaint.urgency, 99),
                -complaint.created_at.timestamp(),
            )
        )

    # Staff see every complaint, not just one flat's, so each row needs its
    # own flat_number to show which flat it came from.
    flats_by_id = {flat.id: flat for flat in db.query(Flat).all()}
    rows = [
        {"complaint": complaint, "flat_number": flats_by_id[complaint.flat_id].flat_number}
        for complaint in complaints
    ]

    return templates.TemplateResponse(
        request,
        "staff_complaints.html",
        {
            "rows": rows,
            "sort": sort,
            "selected_categories": category,
            "selected_statuses": status,
            "all_categories": ALL_CATEGORIES,
            "all_statuses": ALL_STATUSES,
        },
    )


@app.post("/staff/complaints/{complaint_id}/update")
def staff_complaint_update(
    complaint_id: int,
    category: str = Form(...),
    status: str = Form(...),
    user: User = Depends(require_role("staff")),
    db: Session = Depends(get_db),
):
    # This is an internal staff control, not a public form, so on bad input
    # (a tampered request, a stale form from before a category was renamed)
    # we just redirect back to the list rather than showing an error page.
    if category not in ALL_CATEGORIES or status not in ALL_STATUSES:
        return RedirectResponse(url="/staff/complaints", status_code=303)

    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if complaint is None:
        return RedirectResponse(url="/staff/complaints", status_code=303)

    complaint.category = category
    complaint.status = status
    db.commit()

    return RedirectResponse(url="/staff/complaints", status_code=303)

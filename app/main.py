# This is the entry point of the whole app — the file that actually
# starts the FastAPI web server and defines the web pages/routes.

import csv
import io
import os
from datetime import date, datetime

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
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

# Serves files from app/static/ at the URL /static/... — without this,
# base.html's <link href="/static/style.css"> would 404, since FastAPI
# doesn't serve arbitrary folders unless they're explicitly mounted.
app.mount("/static", StaticFiles(directory="app/static"), name="static")


def asset_version(filename: str) -> int:
    # A static file's own last-modified time, used as a cache-busting query
    # string (?v=...) on its <link>/<script> tag in base.html. Without
    # this, browsers that cache static files (they have no Cache-Control
    # header) keep showing an old version after we edit it, until a hard
    # refresh — changing the URL itself every time the file changes forces
    # a refetch instead of relying on everyone remembering to hard-refresh.
    return int(os.path.getmtime(f"app/static/{filename}"))


templates.env.globals["asset_version"] = asset_version


def format_inr(value: float) -> str:
    # Formats a number the way Indian currency is actually grouped —
    # the last 3 digits of the rupee part as one group, then groups of 2
    # going left from there (so 100000 -> "1,00,000", not the Western
    # "100,000") — plus the exact paise as 2 decimal places, since
    # silently rounding those away (e.g. showing 2900.4 as "₹2,900") hid
    # real money from view. Used as the "inr" template filter registered
    # below; every amount shown to a user should go through it instead of
    # printing a raw float.
    sign = "-" if value < 0 else ""

    # Rounding the whole value as paise (value * 100) in one step, rather
    # than separately rounding rupees and subtracting to get paise, avoids
    # float imprecision (e.g. 2900.4 - 2900 isn't exactly 0.4 in binary
    # floating point) ever producing a wrong or inconsistent paise figure.
    total_paise = round(abs(value) * 100)
    rupees, paise = divmod(total_paise, 100)

    digits = str(rupees)
    if len(digits) <= 3:
        grouped = digits
    else:
        last_three = digits[-3:]
        rest = digits[:-3]
        groups = []
        while len(rest) > 2:
            groups.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.insert(0, rest)
        grouped = ",".join(groups) + "," + last_three

    return f"{sign}₹{grouped}.{paise:02d}"


templates.env.filters["inr"] = format_inr

# These must stay in sync with the CheckConstraints on Complaint in
# app/models.py — they're the single source of truth for what's valid;
# these lists are this file's own copy, shared by the resident complaint
# summary and the staff complaints page, to build checkboxes/dropdowns and
# to validate the staff update form against.
ALL_CATEGORIES = [
    "plumbing", "electrical", "lift", "security", "cleaning",
    "safety", "structural", "parking", "noise", "other",
]
ALL_STATUSES = ["Open", "In Progress", "Resolved"]

# Lower number = higher priority. Used to sort complaints by urgency tier.
URGENCY_RANK = {"High": 0, "Medium": 1, "Low": 2}


# @app.get("/") means: when someone visits the home page ("/") with a
# normal browser visit (a GET request), run the function right below it.
@app.get("/")
def home(request: Request):
    role = request.session.get("role")

    if role == "resident":
        return RedirectResponse(url="/bills")
    if role == "staff":
        return RedirectResponse(url="/staff/dashboard")

    # Logged-out visitors see the public homepage instead of being bounced
    # straight to the login form — it's their actual entry point into
    # either the resident or staff login flow below.
    return templates.TemplateResponse(request, "home.html")


@app.get("/login")
def login_page(request: Request):
    # TemplateResponse needs "request" — Starlette uses it internally (e.g.
    # for building URLs), so it's always the first argument passed in.
    return templates.TemplateResponse(request, "login.html")


@app.get("/login/resident")
def login_page_resident(request: Request):
    # Same login.html, same /login POST underneath — this route only picks
    # which heading shows. There's still exactly one place a password is
    # ever checked (the POST /login handler below), not two auth systems.
    return templates.TemplateResponse(request, "login.html", {"audience": "resident"})


@app.get("/login/staff")
def login_page_staff(request: Request):
    return templates.TemplateResponse(request, "login.html", {"audience": "staff"})


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

    # "/" (not "/login" directly) so a logged-out visitor lands back on the
    # public homepage — the same page they'd have seen before ever logging
    # in, with both the Resident Login and Staff Login choices, rather than
    # skipping straight to the plain generic login form.
    return RedirectResponse(url="/", status_code=303)


@app.get("/staff-only")
def staff_only(user: User = Depends(require_role("staff"))):
    return {"message": "you are staff"}


@app.get("/me")
def me(user: User = Depends(get_current_user)):
    return {"email": user.email, "role": user.role}


def build_bills_context(flat: Flat, bill: Bill, db: Session) -> dict:
    # Shared by bills_page() and pay_bill()'s validation-error re-render —
    # both need the exact same "what does this resident see" picture of
    # their bill and open complaints.
    outstanding = bill.amount_due - bill.amount_paid
    # max(0, ...) means "never negative" — if the bill isn't overdue yet,
    # due_date is in the future, and (today - due_date) would be negative.
    days_overdue = max(0, (date.today() - bill.due_date).days)

    # A short, plain-English label instead of making a resident read three
    # raw numbers and work out their own payment status.
    if outstanding <= 0:
        payment_status = "Fully paid"
    elif bill.amount_paid > 0:
        payment_status = "Partially paid"
    else:
        payment_status = "Not yet paid"

    # This resident's own open complaints, worth surfacing right here since
    # the brief calls out "open complaints and their status" as one of the
    # first things a resident should see, not something they have to click
    # through to My Complaints to find.
    open_complaints = (
        db.query(Complaint)
        .filter(Complaint.flat_id == flat.id, Complaint.status.in_(["Open", "In Progress"]))
        .all()
    )
    open_complaints.sort(
        key=lambda complaint: (URGENCY_RANK.get(complaint.urgency, 99), -complaint.created_at.timestamp())
    )

    return {
        "flat": flat,
        "bill": bill,
        "outstanding": outstanding,
        "days_overdue": days_overdue,
        "payment_status": payment_status,
        "is_overdue": days_overdue > 0 and outstanding > 0,
        "open_complaints": open_complaints,
    }


@app.get("/bills")
def bills_page(
    request: Request,
    paid: bool = False,
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

    context = build_bills_context(flat, bill, db)
    context["just_paid"] = paid

    return templates.TemplateResponse(request, "bills.html", context)


@app.get("/staff/dashboard")
def staff_dashboard(
    request: Request,
    user: User = Depends(require_role("staff")),
    db: Session = Depends(get_db),
):
    flats = db.query(Flat).all()

    total_collections = 0
    total_outstanding = 0
    overdue_flats = []

    for flat in flats:
        for bill in flat.bills:
            total_collections += bill.amount_paid
            total_outstanding += max(0, bill.amount_due - bill.amount_paid)

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

    open_complaints = db.query(Complaint).filter(Complaint.status.in_(["Open", "In Progress"])).all()

    open_complaint_count = len(open_complaints)
    open_by_urgency = {"High": 0, "Medium": 0, "Low": 0}
    for complaint in open_complaints:
        open_by_urgency[complaint.urgency] += 1

    now = datetime.utcnow()
    if open_complaints:
        average_open_age_days = sum(
            (now - complaint.created_at).total_seconds() for complaint in open_complaints
        ) / len(open_complaints) / 86400
    else:
        average_open_age_days = 0

    resolved_complaints = db.query(Complaint).filter(Complaint.resolved_at.isnot(None)).all()
    if resolved_complaints:
        average_resolution_days = sum(
            (complaint.resolved_at - complaint.created_at).total_seconds()
            for complaint in resolved_complaints
        ) / len(resolved_complaints) / 86400
    else:
        average_resolution_days = None

    return templates.TemplateResponse(
        request,
        "staff_dashboard.html",
        {
            "total_collections": total_collections,
            "total_outstanding": total_outstanding,
            "overdue_flats": overdue_flats,
            "open_complaint_count": open_complaint_count,
            "open_by_urgency": open_by_urgency,
            "average_open_age_days": average_open_age_days,
            "average_resolution_days": average_resolution_days,
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

    # Re-render the same page with an error instead of applying a payment
    # that doesn't make sense (nothing paid, or paying more than is owed).
    if amount <= 0 or amount > outstanding:
        context = build_bills_context(flat, bill, db)
        context["error"] = "Enter an amount greater than 0 and no more than the outstanding balance"
        return templates.TemplateResponse(request, "bills.html", context)

    bill.amount_paid += amount
    db.commit()

    # ?paid=1 tells the next /bills GET to show a "payment received" banner
    # — this is the "meaningful payment feedback" the brief asks for, since
    # a bare redirect back to the same page gives no visible confirmation
    # that anything happened.
    return RedirectResponse(url="/bills?paid=1", status_code=303)


def escalate_duplicate_cluster_urgency(db: Session, linked_to_id: int, new_complaint: Complaint) -> None:
    # find_duplicate() always returns the OLDEST member of a cluster (the
    # "anchor" — see the duplicate-linking note in decisions.md), so
    # anchor.linked_to_id should already be None. Walking up anyway costs
    # nothing and keeps this correct even if that invariant were ever
    # violated (e.g. a future change, or a manually edited row).
    anchor = db.query(Complaint).filter(Complaint.id == linked_to_id).first()
    while anchor.linked_to_id is not None:
        anchor = db.query(Complaint).filter(Complaint.id == anchor.linked_to_id).first()

    # If root-walking found a deeper anchor than find_duplicate() returned,
    # point the new complaint at that true root instead — keeps every
    # duplicate pointing straight at one original report (a star shape),
    # same reasoning as why linking always targets the oldest complaint.
    new_complaint.linked_to_id = anchor.id

    existing_duplicates = db.query(Complaint).filter(Complaint.linked_to_id == anchor.id).all()
    cluster = [anchor, new_complaint] + existing_duplicates

    # Lower URGENCY_RANK = higher priority, so the cluster's highest
    # urgency is whichever member has the lowest rank.
    highest_urgency = min(cluster, key=lambda complaint: URGENCY_RANK.get(complaint.urgency, 99)).urgency

    # Setting every member to the single highest urgency in the cluster can
    # only raise or leave unchanged each individual complaint's urgency —
    # never lower it — which is exactly the "never downgrade" rule.
    for complaint in cluster:
        complaint.urgency = highest_urgency

    # Same reasoning for the safety flag: it's one real-world problem, so if
    # any report in the cluster tripped the safety check (e.g. the one that
    # says "gas leak"), a sibling describing it in different words ("smell
    # near my flat") must not show up as a plain, un-alerted complaint.
    if any(complaint.is_safety_flagged for complaint in cluster):
        for complaint in cluster:
            complaint.is_safety_flagged = True


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

    if linked_to_id is not None:
        escalate_duplicate_cluster_urgency(db, linked_to_id, complaint)

    db.add(complaint)
    db.commit()

    # ?submitted=1 tells the next /complaints GET to show a confirmation
    # banner — without it, submitting a complaint gives no visible sign
    # that anything actually happened.
    return RedirectResponse(url="/complaints?submitted=1", status_code=303)


def build_duplicate_links(db: Session, complaint: Complaint) -> dict:
    # Shared by the resident /complaints page and the staff /staff/complaints
    # page — both need the same "what is this complaint's place in its
    # duplicate cluster, if any" picture.
    #
    # The complaint this one was linked to as a duplicate (if any) — looked
    # up fresh each time, by id, rather than relying on a relationship,
    # since linked_to_id can point at a complaint belonging to a different
    # flat.
    linked_from = None
    if complaint.linked_to_id is not None:
        linked_from = db.query(Complaint).filter(Complaint.id == complaint.linked_to_id).first()

    # Other complaints that point back at THIS one — i.e. this complaint is
    # the "original" and these are its duplicates.
    linked_duplicates = db.query(Complaint).filter(Complaint.linked_to_id == complaint.id).all()

    return {"linked_from": linked_from, "linked_duplicates": linked_duplicates}


def get_cluster_siblings(db: Session, complaint: Complaint) -> list[Complaint]:
    # Every OTHER complaint in the same duplicate cluster as this one,
    # regardless of whether this complaint is the anchor or one of its
    # duplicates. Used to warn staff that related reports exist after they
    # change a complaint's status — not to change those reports themselves.
    anchor_id = complaint.linked_to_id if complaint.linked_to_id is not None else complaint.id

    cluster = (
        db.query(Complaint)
        .filter((Complaint.id == anchor_id) | (Complaint.linked_to_id == anchor_id))
        .all()
    )
    return [member for member in cluster if member.id != complaint.id]


@app.get("/complaints")
def complaint_list(
    request: Request,
    submitted: bool = False,
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
        row = {"complaint": complaint}
        row.update(build_duplicate_links(db, complaint))
        rows.append(row)

    return templates.TemplateResponse(request, "complaint_list.html", {"rows": rows, "just_submitted": submitted})


@app.get("/staff/complaints")
def staff_complaints_page(
    request: Request,
    sort: str = "urgency",
    category: list[str] = Query(default=[]),
    status: list[str] = Query(default=[]),
    status_changed_id: int | None = None,
    user: User = Depends(require_role("staff")),
    db: Session = Depends(get_db),
):
    # Set by staff_complaint_update() right after a status change on a
    # complaint that's part of a duplicate cluster — a reminder banner, not
    # an automatic change to the sibling complaints themselves.
    status_change_notice = None
    if status_changed_id is not None:
        changed_complaint = db.query(Complaint).filter(Complaint.id == status_changed_id).first()
        if changed_complaint is not None:
            siblings = get_cluster_siblings(db, changed_complaint)
            if siblings:
                status_change_notice = {"complaint": changed_complaint, "siblings": siblings}

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
    rows = []
    for complaint in complaints:
        row = {"complaint": complaint, "flat_number": flats_by_id[complaint.flat_id].flat_number}
        row.update(build_duplicate_links(db, complaint))
        rows.append(row)

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
            "status_change_notice": status_change_notice,
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

    status_changed = status != complaint.status

    # resolved_at tracks when the complaint most recently BECAME resolved —
    # it only gets set on the actual Open/In Progress -> Resolved transition
    # (not on every save while it's already Resolved, which would keep
    # pushing the timestamp forward), and gets cleared the moment it's
    # anything other than Resolved, so a reopened-then-resolved complaint
    # gets a fresh, accurate timestamp instead of its old one.
    if status == "Resolved":
        if complaint.status != "Resolved":
            complaint.resolved_at = datetime.utcnow()
    else:
        complaint.resolved_at = None

    complaint.category = category
    complaint.status = status
    db.commit()

    # If the status actually changed and this complaint is part of a
    # duplicate cluster, nudge staff to go check whether the related
    # reports need the same status update too — a reminder only, nothing
    # is changed automatically for them.
    if status_changed and get_cluster_siblings(db, complaint):
        return RedirectResponse(url=f"/staff/complaints?status_changed_id={complaint.id}", status_code=303)

    return RedirectResponse(url="/staff/complaints", status_code=303)

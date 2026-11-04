# This is the entry point of the whole app — the file that actually
# starts the FastAPI web server and defines the web pages/routes.

import os

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app.auth import verify_password
from app.database import Base, engine, get_db

# We import Bill, Flat, User here even though we never use them by name in
# this file. Why: Base.metadata.create_all() below only creates tables for
# models that Python has actually "seen" (imported) somewhere. If we didn't
# import them here, Python might never load app/models.py, and create_all
# would create ZERO tables, silently. The "# noqa: F401" comment just tells
# code-checking tools "yes, I know this import looks unused, that's on purpose".
from app.models import Bill, Flat, User  # noqa: F401

# This line runs once, when the app starts up. It checks society.db: for
# every table that doesn't exist yet (users, flats, bills), it creates it.
# If the tables already exist, it does nothing to them (it won't update
# a table even if we've changed the model since — more on that if we hit it).
Base.metadata.create_all(bind=engine)

# load_dotenv() reads the .env file in the project root and makes its
# values available via os.getenv(), as if they were set in the environment.
# .env is in .gitignore on purpose: it holds secrets that shouldn't be
# committed to git.
load_dotenv()

# This is the actual FastAPI application object. Everything below this
# line is defining what the app can do.
app = FastAPI()

# SessionMiddleware lets us store small bits of data (like "this browser is
# logged in as user X") in a signed cookie on the user's browser, between
# requests. "Signed" means the cookie's contents can't be tampered with
# without knowing secret_key — that's why secret_key comes from .env instead
# of being hardcoded here.
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SECRET_KEY"))

# Jinja2Templates lets us render .html files from app/templates/ as actual
# web pages, instead of just returning JSON like the "/" route below does.
templates = Jinja2Templates(directory="app/templates")


# @app.get("/") means: when someone visits the home page ("/") with a
# normal browser visit (a GET request), run the function right below it.
@app.get("/")
def home():
    return {"message": "hello from society app"}


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

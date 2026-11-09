"""
=============================================================================
WHAT IS THIS FILE?
=============================================================================
conftest.py is a special file name that pytest (our test runner) loads
automatically before running any test. It is the place to put "fixtures".

A FIXTURE is a reusable piece of test setup. Think of it as a helper that
prepares things (a database, a logged-in user, a bill...) so each test does
not have to repeat that work.

HOW FIXTURES GET USED:
If a test function lists a fixture's name as a parameter, pytest runs that
fixture first and passes the result in. For example:

    def test_something(bill):      <- pytest sees "bill", runs the bill fixture
        print(bill.amount_due)     <- and hands the finished Bill to the test

Fixtures can also use other fixtures (the "bill" fixture below asks for
"db_session" and "flat"), so they build on each other like layers.
=============================================================================
"""

import os

"""
app/main.py raises at import time if SECRET_KEY is missing, and a real .env
may not exist on CI, so give tests their own throwaway one before importing.

os.environ is a dictionary of environment variables (settings that live
outside the code). setdefault means "only set this if it is not set already".
This line MUST come before the "from app.main import app" line further down,
because importing app.main is what checks for SECRET_KEY.
"""
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient  # pretends to be a browser talking to our app
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.database import Base, get_db
from app.main import app
from app.models import Bill, Flat, User

# Constants (names in CAPITAL LETTERS are a Python habit meaning "this value
# never changes"). Defined once here so every test uses the same login details.
RESIDENT_EMAIL = "resident@test.com"
STAFF_EMAIL = "staff@test.com"
PASSWORD = "testpass123"


# @pytest.fixture is a "decorator": a label placed above a function that tells
# pytest "this function is a fixture, not a normal test".
@pytest.fixture
def db_session():
    """
    Gives every test its own brand new, empty database to work with.

    In-memory SQLite with StaticPool: every connection shares one database,
    which TestClient needs because it runs routes on a different thread.
    Created fresh for each test and discarded afterwards, society.db is
    never touched by a test run.

    In plain words: "sqlite://" means the database lives only in memory (RAM),
    not in a file. When the test ends it vanishes, so tests can never mess up
    your real data and never affect each other.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Create all the tables (flats, bills, users, complaints...) in the empty DB.
    Base.metadata.create_all(bind=engine)
    # A "session" is the object we use to add, read and save rows in the DB.
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSession()

    def override_get_db():
        """
        The real app gets its database through get_db(). Here we define a
        replacement that hands out our in-memory test session instead.
        "yield" is like "return", but the function can continue afterwards.
        """
        yield session

    # Tell FastAPI: "whenever a route asks for get_db, use override_get_db".
    # This is how the app talks to the test database instead of the real one.
    app.dependency_overrides[get_db] = override_get_db

    """
    "yield" in a fixture is the dividing line:
      - code ABOVE it is setup (runs before the test)
      - the value after yield is given to the test
      - code BELOW it is cleanup (runs after the test, even if it failed)
    """
    yield session

    # ---- cleanup: undo everything so the next test starts clean ----
    app.dependency_overrides.clear()
    session.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def client(db_session):
    """
    Anonymous client: no login cookie.
    TestClient(app) acts like a browser: client.get("/bills") sends a request
    to our app without starting a real server. This one is NOT logged in.
    """
    return TestClient(app)


@pytest.fixture
def flat(db_session):
    # Creates one flat (apartment) and saves it into the test database.
    flat = Flat(
        flat_number="T07-1203",
        owner_name="Test Owner",
        area_sqft=1000,
        upi_id="owner@upi",
    )
    db_session.add(flat)  # stage the new row
    db_session.commit()  # actually save it to the database
    return flat


@pytest.fixture
def bill(db_session, flat):
    """
    A bill for the flat above. Notice this fixture asks for "flat", so
    pytest creates the flat first automatically.

    Due 10 days ago, nothing paid yet: outstanding is 6500.
    (date.today() - timedelta(days=10) means "today minus 10 days".)
    """
    bill = Bill(
        flat_id=flat.id,
        amount_due=6500.0,
        amount_paid=0,
        due_date=date.today() - timedelta(days=10),
    )
    db_session.add(bill)
    db_session.commit()
    return bill


@pytest.fixture
def resident_user(db_session, flat):
    # A user account with the "resident" role, living in the flat above.
    # The password is stored hashed (scrambled), exactly like the real app does.
    user = User(
        email=RESIDENT_EMAIL,
        hashed_password=hash_password(PASSWORD),
        role="resident",
        flat_id=flat.id,
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def staff_user(db_session):
    # A user account with the "staff" role. Staff do not belong to any flat,
    # so there is no flat_id here.
    user = User(
        email=STAFF_EMAIL,
        hashed_password=hash_password(PASSWORD),
        role="staff",
    )
    db_session.add(user)
    db_session.commit()
    return user


"""
A function whose name starts with an underscore (_) is a Python convention
meaning "private helper, only used inside this file". It is NOT a fixture
and NOT a test, just a normal function reused by the two fixtures below.
"""
def _logged_in_client(email):
    # A separate TestClient per role so cookies from one login never leak
    # into another client in the same test.
    test_client = TestClient(app)
    # Submit the login form like a browser would. follow_redirects=False means
    # "do not automatically follow the redirect", so we can inspect it.
    response = test_client.post(
        "/login", data={"email": email, "password": PASSWORD}, follow_redirects=False
    )
    """
    303 = "login worked, go to another page". If it is not 303, stop at once
    with the message after the comma. The client now remembers the login
    cookie, so later requests from it count as "logged in".
    """
    assert response.status_code == 303, "test login failed, check the fixtures"
    return test_client


@pytest.fixture
def resident_client(resident_user):
    # A "browser" that is already logged in as the resident.
    return _logged_in_client(RESIDENT_EMAIL)


@pytest.fixture
def staff_client(staff_user):
    # A "browser" that is already logged in as a staff member.
    return _logged_in_client(STAFF_EMAIL)

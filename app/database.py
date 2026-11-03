# This file's only job is to set up ONE connection to our database file
# (society.db) and give the rest of the app a standard way to "borrow" it.
# Every other file that needs to talk to the database imports from here.

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# This is just the address of our database. "sqlite:///society.db" means:
# use SQLite (a database that lives in a single file, no server needed),
# and the file is called society.db, sitting in this project's folder.
DATABASE_URL = "sqlite:///society.db"

# The "engine" is the actual live connection to that database file.
# connect_args={"check_same_thread": False} is a SQLite-specific setting:
# normally SQLite complains if more than one thread tries to use the same
# connection, but FastAPI handles web requests on different threads, so we
# turn that check off.
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

# SessionLocal is a "session factory" — think of it as a machine that hands
# out a fresh session every time we call SessionLocal(). A session is like
# a temporary workspace: you read/add/change rows in it, and nothing is
# permanently saved until you call .commit() on that session.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base is a special class with no data of its own. Its only purpose is to
# be inherited. Any class that writes "class Something(Base):" automatically
# becomes a database table (see app/models.py for examples: User, Flat, Bill).
Base = declarative_base()


# get_db() is written specifically for FastAPI to use as a "dependency".
# FastAPI will call this before running a route that needs the database,
# hand the route the session (via "yield db"), and once the route is done,
# automatically run the code after yield — which closes the session. This
# way every web request gets its own clean session, and we never forget to
# close one.
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

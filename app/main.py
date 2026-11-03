# This is the entry point of the whole app — the file that actually
# starts the FastAPI web server and defines the web pages/routes.

from fastapi import FastAPI

from app.database import Base, engine

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

# This is the actual FastAPI application object. Everything below this
# line is defining what the app can do.
app = FastAPI()


# @app.get("/") means: when someone visits the home page ("/") with a
# normal browser visit (a GET request), run the function right below it.
@app.get("/")
def home():
    return {"message": "hello from society app"}

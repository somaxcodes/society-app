from fastapi import FastAPI

from app.database import Base, engine
from app.models import Bill, Flat, User  # noqa: F401 (needed so Base knows these tables exist)

Base.metadata.create_all(bind=engine)

app = FastAPI()


@app.get("/")
def home():
    return {"message": "hello from society app"}
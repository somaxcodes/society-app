from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = "sqlite:///society.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

# a session that is created every time I want to make changes to a DB
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# any class that inherits Base gets automatically turned into a database table
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

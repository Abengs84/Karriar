from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/karriar.db")

engine = create_engine(
    DATABASE_URL,
    connect_args=(
        {"check_same_thread": False}
        if DATABASE_URL.startswith("sqlite")
        else {}
    ),
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from sqlalchemy import inspect, text

    from app import models  # noqa: F401

    os.makedirs("data", exist_ok=True)

    # Migrera bort gammal pass_number-kolumn (Excel-val ≠ tidspass)
    insp = inspect(engine)
    if insp.has_table("placements"):
        cols = {c["name"] for c in insp.get_columns("placements")}
        if "pass_number" in cols:
            with engine.begin() as conn:
                conn.execute(text("DROP TABLE placements"))

    Base.metadata.create_all(bind=engine)

    from app.seed_rooms import seed_academill_rooms

    db = SessionLocal()
    try:
        seed_academill_rooms(db)
    finally:
        db.close()

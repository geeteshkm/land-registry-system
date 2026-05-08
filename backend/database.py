from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.exc import OperationalError
from dotenv import load_dotenv
import os

PROJECT_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=PROJECT_DIR / ".env")

DATABASE_URL = os.getenv("DATABASE_URL")
SQLITE_PATH = PROJECT_DIR / "land_registry.db"

if DATABASE_URL:
    try:
        engine = create_engine(
            DATABASE_URL,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
        )
        # Verify connectivity once so invalid DB credentials fail fast and fallback safely.
        with engine.connect() as conn:
            pass
    except OperationalError as err:
        print(
            "[WARN] Could not connect to DATABASE_URL. Falling back to local SQLite."
        )
        print(f"[WARN] Postgres error: {err}")
        DATABASE_URL = f"sqlite:///{SQLITE_PATH}"
        engine = create_engine(
            DATABASE_URL,
            connect_args={"check_same_thread": False},
            pool_pre_ping=True,
        )
else:
    DATABASE_URL = f"sqlite:///{SQLITE_PATH}"
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )
    print(f"[INFO] No DATABASE_URL configured. Using fallback SQLite database at {SQLITE_PATH}.")

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

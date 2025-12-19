"""
PLanalyst — FastAPI: Database Connection

SQLAlchemy engine and session management for the serving layer.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from planalyst.config import SQLALCHEMY_CONNECTION_STRING

engine = create_engine(SQLALCHEMY_CONNECTION_STRING, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """FastAPI dependency: yield a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

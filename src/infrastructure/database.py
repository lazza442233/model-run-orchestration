from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session, DeclarativeBase
from src.config import settings

# Create engine
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    echo=(settings.LOG_LEVEL.upper() == "DEBUG")
)

# Create session factory
SessionFactory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Thread-safe session registry (good for Flask)
Session = scoped_session(SessionFactory)

# Modern SQLAlchemy 2.0 Declarative Base


class Base(DeclarativeBase):
    """
    Subclassing DeclarativeBase is the modern (2.0+) way to define the ORM base.
    It provides better static typing support than declarative_base().
    """
    pass


def init_db():
    import src.infrastructure.models  # noqa: F401
    Base.metadata.create_all(bind=engine)


def get_db():
    """Dependency injection helper"""
    db = Session()
    try:
        yield db
    finally:
        db.close()

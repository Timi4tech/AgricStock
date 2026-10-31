import os
from collections.abc import Generator
from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./agrostock_dev.db")
IS_SQLITE = DATABASE_URL.startswith("sqlite")
connect_args = {"check_same_thread": False} if IS_SQLITE else {}
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    connect_args=connect_args,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def _backfill_legacy_ownership(connection, table_name: str) -> None:
    """Backfill old ownerless rows only when ownership is unambiguous."""
    inspector = inspect(connection)
    if table_name not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns(table_name)}
    if "user_id" not in columns:
        if IS_SQLITE:
            connection.execute(text(f'ALTER TABLE "{table_name}" ADD COLUMN user_id INTEGER'))
        else:
            connection.execute(text(
                f'ALTER TABLE "{table_name}" ADD COLUMN user_id INTEGER '
                'REFERENCES users(id) ON DELETE CASCADE'
            ))
        columns.add("user_id")

    # Movement rows can inherit ownership from their item, even if several users exist.
    if table_name == "stock_movements" and "item_id" in columns:
        connection.execute(text(
            "UPDATE stock_movements SET user_id = (SELECT inventory_items.user_id "
            "FROM inventory_items WHERE inventory_items.id = stock_movements.item_id) "
            "WHERE user_id IS NULL"
        ))

    null_count = connection.execute(text(f'SELECT COUNT(*) FROM "{table_name}" WHERE user_id IS NULL')).scalar_one()
    if null_count:
        user_count = connection.execute(text("SELECT COUNT(*) FROM users")).scalar_one()
        if user_count == 1:
            only_user_id = connection.execute(text("SELECT id FROM users ORDER BY id LIMIT 1")).scalar_one()
            connection.execute(text(f'UPDATE "{table_name}" SET user_id = :uid WHERE user_id IS NULL'), {"uid": only_user_id})
        else:
            raise RuntimeError(
                f"Schema migration found {null_count} ownerless rows in {table_name}. "
                "The user_id column was added, but automatic ownership is ambiguous because "
                "the database does not contain exactly one user. Assign those legacy rows to "
                "the correct users before restarting the API."
            )

    if not IS_SQLITE:
        connection.execute(text(f'ALTER TABLE "{table_name}" ALTER COLUMN user_id SET NOT NULL'))
    connection.execute(text(f'CREATE INDEX IF NOT EXISTS ix_{table_name}_user_id ON "{table_name}" (user_id)'))


def initialize_database() -> None:
    """Create missing tables, then safely migrate owner columns on existing installations.

    This small startup migration covers ownership-column additions. For future structural
    changes, use versioned Alembic migrations rather than relying on create_all.
    """
    from .domain import models  # noqa: F401 - register all models
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        _backfill_legacy_ownership(connection, "inventory_items")
        _backfill_legacy_ownership(connection, "stock_movements")


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

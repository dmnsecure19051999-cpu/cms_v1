from datetime import datetime
from sqlalchemy import (create_engine, text, inspect as sa_inspect,
                         MetaData, Table, Column, Integer, String, DateTime, Engine)

STATUS_SUCCESS = "success"

_ALLOWED_COL_TYPES = {"NVARCHAR(MAX)", "TEXT", "INTEGER", "FLOAT", "DATETIME"}


def get_engine(db_url: str) -> Engine:
    return create_engine(db_url)


def create_metadata_tables(engine: Engine):
    meta = MetaData()
    Table("_load_metadata", meta,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("file_path", String(500), nullable=False),
        Column("table_name", String(100)),
        Column("last_loaded_at", DateTime),
        Column("row_count", Integer),
        Column("status", String(20)),
    )
    Table("_run_log", meta,
        Column("run_id", Integer, primary_key=True, autoincrement=True),
        Column("mode", String(10)),
        Column("started_at", DateTime),
        Column("finished_at", DateTime),
        Column("files_processed", Integer, default=0),
        Column("files_skipped", Integer, default=0),
        Column("errors", Integer, default=0),
    )
    meta.create_all(engine, checkfirst=True)


def get_table_columns(engine: Engine, table_name: str) -> list[str]:
    insp = sa_inspect(engine)
    if not insp.has_table(table_name):
        return []
    return [col["name"] for col in insp.get_columns(table_name)]


def add_column(engine: Engine, table_name: str, col_name: str, col_type: str = "NVARCHAR(MAX)"):
    if col_type.upper() not in _ALLOWED_COL_TYPES:
        raise ValueError(f"Unsupported col_type: {col_type!r}")
    with engine.connect() as conn:
        conn.execute(text(f'ALTER TABLE "{table_name}" ADD "{col_name}" {col_type}'))
        conn.commit()


def get_last_run_time(engine: Engine) -> datetime | None:
    with engine.connect() as conn:
        row = conn.execute(text("SELECT MAX(started_at) FROM _run_log")).fetchone()
        return row[0] if row and row[0] is not None else None


def upsert_load_metadata(engine: Engine, file_path: str, table_name: str,
                          row_count: int, status: str):
    with engine.connect() as conn:
        existing = conn.execute(text(
            "SELECT id FROM _load_metadata WHERE file_path = :fp"
        ), {"fp": file_path}).fetchone()
        if existing:
            conn.execute(text("""
                UPDATE _load_metadata
                SET last_loaded_at = :now, row_count = :rc, status = :st
                WHERE file_path = :fp
            """), {"now": datetime.now(), "rc": row_count, "st": status, "fp": file_path})
        else:
            conn.execute(text("""
                INSERT INTO _load_metadata (file_path, table_name, last_loaded_at, row_count, status)
                VALUES (:fp, :tn, :now, :rc, :st)
            """), {"fp": file_path, "tn": table_name, "now": datetime.now(),
                   "rc": row_count, "st": status})
        conn.commit()


def is_file_loaded(engine: Engine, file_path: str) -> bool:
    with engine.connect() as conn:
        row = conn.execute(text(
            f"SELECT id FROM _load_metadata WHERE file_path = :fp AND status = '{STATUS_SUCCESS}'"
        ), {"fp": file_path}).fetchone()
        return row is not None


def insert_run_log(engine: Engine, mode: str, started_at: datetime) -> int:
    with engine.connect() as conn:
        result = conn.execute(text(
            "INSERT INTO _run_log (mode, started_at) VALUES (:mode, :started_at)"
        ), {"mode": mode, "started_at": started_at})
        conn.commit()
        return result.lastrowid


def finish_run_log(engine: Engine, run_id: int, processed: int, skipped: int, errors: int):
    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE _run_log
            SET finished_at = :now, files_processed = :p, files_skipped = :s, errors = :e
            WHERE run_id = :rid
        """), {"now": datetime.now(), "p": processed, "s": skipped, "e": errors, "rid": run_id})
        conn.commit()

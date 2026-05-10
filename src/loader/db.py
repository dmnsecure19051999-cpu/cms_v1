from datetime import datetime
from sqlalchemy import (create_engine, text, inspect as sa_inspect,
                         MetaData, Table, Column, Integer, String, DateTime, Engine,
                         insert as sa_insert)

STATUS_SUCCESS = "success"

_ALLOWED_COL_TYPES = {"TEXT", "INTEGER", "FLOAT", "TIMESTAMP"}
_UPGRADE_SKIP_COLS = {"source_file", "uuid"}


def get_engine(db_url: str) -> Engine:
    return create_engine(db_url)


def ensure_database(db_url: str):
    from sqlalchemy.engine import make_url
    from sqlalchemy import event
    u = make_url(db_url)
    db_name = u.database
    admin_url = u.set(database="postgres")
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": db_name}
        ).fetchone()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    engine.dispose()


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


def add_column(engine: Engine, table_name: str, col_name: str, col_type: str = "TEXT"):
    if col_type.upper() not in _ALLOWED_COL_TYPES:
        raise ValueError(f"Unsupported col_type: {col_type!r}")
    with engine.connect() as conn:
        conn.execute(text(f'ALTER TABLE "{table_name}" ADD "{col_name}" {col_type}'))
        conn.commit()


def drop_table(engine: Engine, table_name: str):
    with engine.connect() as conn:
        conn.execute(text(f'DROP TABLE IF EXISTS "{table_name}"'))
        conn.commit()


_UPGRADE_CANDIDATE_TYPES = ("NUMERIC", "TIMESTAMP")


def upgrade_column_types(engine: Engine, table_name: str, logger=None,
                          cols: list[str] | None = None):
    all_cols = get_table_columns(engine, table_name)
    if not all_cols:
        if logger:
            logger.warning(f"TYPE_UPGRADE — {table_name} not found, skipping")
        return
    target_cols = cols if cols is not None else all_cols
    for col in target_cols:
        if col in _UPGRADE_SKIP_COLS:
            continue
        for sql_type in _UPGRADE_CANDIDATE_TYPES:
            try:
                with engine.connect() as conn:
                    conn.execute(text(
                        f'ALTER TABLE "{table_name}" '
                        f'ALTER COLUMN "{col}" TYPE {sql_type} '
                        f'USING "{col}"::{sql_type}'
                    ))
                    conn.commit()
                if logger:
                    logger.info(f"TYPE_UPGRADE — {table_name}.{col} → {sql_type}")
                break
            except Exception as e:
                if logger:
                    logger.debug(f"SKIP_UPGRADE — {table_name}.{col} → {sql_type}: {e}")


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
            "SELECT id FROM _load_metadata WHERE file_path = :fp AND status = :status"
        ), {"fp": file_path, "status": STATUS_SUCCESS}).fetchone()
        return row is not None


def insert_run_log(engine: Engine, mode: str, started_at: datetime) -> int:
    with engine.connect() as conn:
        meta = MetaData()
        meta.reflect(bind=engine, only=["_run_log"])
        run_log_tbl = meta.tables["_run_log"]
        result = conn.execute(
            sa_insert(run_log_tbl).values(mode=mode, started_at=started_at)
        )
        conn.commit()
        return result.inserted_primary_key[0]


def finish_run_log(engine: Engine, run_id: int, processed: int, skipped: int, errors: int):
    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE _run_log
            SET finished_at = :now, files_processed = :p, files_skipped = :s, errors = :e
            WHERE run_id = :rid
        """), {"now": datetime.now(), "p": processed, "s": skipped, "e": errors, "rid": run_id})
        conn.commit()

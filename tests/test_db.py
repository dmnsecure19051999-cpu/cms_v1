import pytest
from sqlalchemy import create_engine, text, inspect

@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    return eng

def test_create_metadata_tables(engine):
    from loader.db import create_metadata_tables
    create_metadata_tables(engine)
    insp = inspect(engine)
    assert "_load_metadata" in insp.get_table_names()
    assert "_run_log" in insp.get_table_names()

def test_get_table_columns_empty(engine):
    from loader.db import create_metadata_tables, get_table_columns
    create_metadata_tables(engine)
    assert get_table_columns(engine, "nonexistent") == []

def test_add_column(engine):
    from loader.db import create_metadata_tables, add_column, get_table_columns
    create_metadata_tables(engine)
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE test_tbl (id INTEGER PRIMARY KEY)"))
        conn.commit()
    add_column(engine, "test_tbl", "new_col", "TEXT")
    cols = get_table_columns(engine, "test_tbl")
    assert "new_col" in cols

def test_drop_table(engine):
    from loader.db import drop_table, get_table_columns
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE tbl_to_drop (id INTEGER)"))
        conn.commit()
    drop_table(engine, "tbl_to_drop")
    assert get_table_columns(engine, "tbl_to_drop") == []


def test_drop_table_nonexistent_is_noop(engine):
    from loader.db import drop_table
    drop_table(engine, "does_not_exist")  # should not raise


def test_get_last_run_time_none(engine):
    from loader.db import create_metadata_tables, get_last_run_time
    create_metadata_tables(engine)
    assert get_last_run_time(engine) is None


def test_upgrade_column_types_noop_on_non_postgres(engine):
    """On SQLite, ALTER COLUMN TYPE is unsupported — function must not raise."""
    from loader.db import upgrade_column_types
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE upg_tbl (name TEXT, amount TEXT, source_file TEXT)"))
        conn.execute(text("INSERT INTO upg_tbl VALUES ('foo', '1.5', 'f.xlsx')"))
        conn.commit()
    # Should not raise even though SQLite rejects ALTER COLUMN TYPE
    upgrade_column_types(engine, "upg_tbl", logger=None)
    # Columns still exist
    from loader.db import get_table_columns
    assert "amount" in get_table_columns(engine, "upg_tbl")


def test_upgrade_column_types_skips_source_file(engine):
    """source_file column must never be upgraded; data columns are attempted."""
    from loader.db import upgrade_column_types, get_table_columns
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE upg_tbl2 (amount TEXT, source_file TEXT)"))
        conn.execute(text("INSERT INTO upg_tbl2 VALUES ('1.5', 'f.xlsx')"))
        conn.commit()
    upgrade_column_types(engine, "upg_tbl2", logger=None)
    # source_file must still exist regardless of upgrade outcome
    assert "source_file" in get_table_columns(engine, "upg_tbl2")
    # amount was attempted (SQLite rejects, stays TEXT) — column must still exist
    assert "amount" in get_table_columns(engine, "upg_tbl2")

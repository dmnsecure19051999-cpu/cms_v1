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

def test_get_last_run_time_none(engine):
    from loader.db import create_metadata_tables, get_last_run_time
    create_metadata_tables(engine)
    assert get_last_run_time(engine) is None

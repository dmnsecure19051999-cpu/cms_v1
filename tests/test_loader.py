import pandas as pd
import pytest
from sqlalchemy import create_engine, text, inspect as sa_inspect


@pytest.fixture
def engine():
    return create_engine("sqlite:///:memory:")


def test_load_new_file(engine):
    from loader.loader import load_file
    from loader.db import create_metadata_tables
    create_metadata_tables(engine)
    df = pd.DataFrame({"bill_id": [1, 2], "amount": [100.0, 200.0]})
    stats = load_file(engine, df, "cancellation_bills", "cancel/test.xlsx", logger=None)
    assert stats["loaded"] == 2
    assert stats["skipped"] == 0


def test_load_adds_source_file_column(engine):
    from loader.loader import load_file
    from loader.db import create_metadata_tables
    create_metadata_tables(engine)
    df = pd.DataFrame({"bill_id": [1], "amount": [100.0]})
    load_file(engine, df, "cancellation_bills", "cancel/test.xlsx", logger=None)
    cols = [c["name"] for c in sa_inspect(engine).get_columns("cancellation_bills")]
    assert "source_file" in cols


def test_reload_deletes_old_rows(engine):
    from loader.loader import load_file
    from loader.db import create_metadata_tables
    create_metadata_tables(engine)
    df1 = pd.DataFrame({"bill_id": [1, 2], "amount": [100.0, 200.0]})
    load_file(engine, df1, "cancellation_bills", "cancel/test.xlsx", logger=None)
    df2 = pd.DataFrame({"bill_id": [3], "amount": [300.0]})
    load_file(engine, df2, "cancellation_bills", "cancel/test.xlsx", logger=None)
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM cancellation_bills")).scalar()
    assert count == 1


def test_ensure_schema_creates_all_text_columns(engine):
    """_ensure_table_schema must create columns as TEXT, never infer numeric types."""
    from loader.loader import load_file
    from loader.db import create_metadata_tables
    from sqlalchemy import inspect as sa_inspect
    create_metadata_tables(engine)
    df = pd.DataFrame({"amount": [1.0, 2.0], "note": ["a", "b"]})
    load_file(engine, df, "test_tbl", "f.xlsx", logger=None)
    col_types = {c["name"]: str(c["type"]).upper()
                 for c in sa_inspect(engine).get_columns("test_tbl")}
    assert "TEXT" in col_types["amount"]
    assert "TEXT" in col_types["note"]


def test_skip_row_on_bad_data(engine):
    from loader.loader import load_file
    from loader.db import create_metadata_tables
    create_metadata_tables(engine)
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE cancellation_bills (bill_id INTEGER, amount FLOAT, source_file TEXT)"))
        conn.commit()
    df = pd.DataFrame({"bill_id": [1, 2], "amount": ["not_a_number", 200.0]})
    stats = load_file(engine, df, "cancellation_bills", "cancel/test.xlsx", logger=None)
    assert stats["skipped"] >= 1



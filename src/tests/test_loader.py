import logging
import os
import tempfile

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


def _make_xlsx(tmp_dir, filename, columns):
    """Helper: create a minimal xlsx with given column headers."""
    path = os.path.join(tmp_dir, filename)
    pd.DataFrame({c: [] for c in columns}).to_excel(path, index=False)
    return path


def test_build_table_schemas_creates_tables(engine):
    from loader.loader import build_table_schemas
    from loader.db import create_metadata_tables, get_table_columns

    create_metadata_tables(engine)

    with tempfile.TemporaryDirectory() as tmp:
        f1 = _make_xlsx(tmp, "a.xlsx", ["Bill ID", "Amount"])
        f2 = _make_xlsx(tmp, "b.xlsx", ["Bill ID", "Note"])

        files = [
            {"file_path": f1, "rel_path": "cancel/a.xlsx", "table_name": "cancel_tbl"},
            {"file_path": f2, "rel_path": "cancel/b.xlsx", "table_name": "cancel_tbl"},
        ]

        class FakeCfg:
            table_header_map = {}

        logger = logging.getLogger("test")
        to_load, n_skipped = build_table_schemas(engine, files, FakeCfg(), logger)

    assert n_skipped == 0
    assert len(to_load) == 2
    cols = get_table_columns(engine, "cancel_tbl")
    assert "bill_id" in cols    # normalized
    assert "amount" in cols
    assert "note" in cols
    assert "source_file" in cols


def test_build_table_schemas_skips_bad_file(engine):
    from loader.loader import build_table_schemas
    from loader.db import create_metadata_tables

    create_metadata_tables(engine)

    files = [
        {"file_path": "/nonexistent/bad.xlsx", "rel_path": "cancel/bad.xlsx",
         "table_name": "cancel_tbl"},
    ]

    class FakeCfg:
        table_header_map = {}

    import logging
    logger = logging.getLogger("test")
    to_load, n_skipped = build_table_schemas(engine, files, FakeCfg(), logger)

    assert n_skipped == 1
    assert len(to_load) == 0


def test_load_large_file_bulk(engine):
    """Files with >500 rows should be inserted via bulk path."""
    from loader.loader import load_file
    from loader.db import create_metadata_tables
    create_metadata_tables(engine)
    df = pd.DataFrame({"bill_id": list(range(600)), "amount": [1.0] * 600})
    stats = load_file(engine, df, "cancellation_bills", "cancel/big.xlsx", logger=None)
    assert stats["loaded"] == 600
    assert stats["skipped"] == 0
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM cancellation_bills")).scalar()
    assert count == 600


def test_load_file_deduplicates_normalized_columns(engine):
    """Two raw columns normalizing to the same name must not cause duplicate-column INSERT error."""
    from loader.loader import load_file
    from loader.db import create_metadata_tables
    create_metadata_tables(engine)
    # "Note" and "Note " both normalize to "note" — first occurrence wins
    df = pd.DataFrame({"ID": [1, 2], "Note": ["a", "b"], "Note ": ["x", "y"]})
    stats = load_file(engine, df, "dedup_tbl", "test/dedup.xlsx", logger=None)
    assert stats["loaded"] == 2
    assert stats["skipped"] == 0


def test_load_file_logs_insert_operation(engine):
    from loader.loader import load_file
    from loader.db import create_metadata_tables
    create_metadata_tables(engine)
    df = pd.DataFrame({"bill_id": [1, 2], "amount": [100.0, 200.0]})
    load_file(engine, df, "cancellation_bills", "cancel/test.xlsx", logger=None)
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT operation FROM _load_metadata
            WHERE file_path = 'cancel/test.xlsx'
            ORDER BY last_loaded_at DESC LIMIT 1
        """)).fetchone()
    assert row[0] == "INSERT"


def test_load_file_logs_update_operation_on_reload(engine):
    from loader.loader import load_file
    from loader.db import create_metadata_tables
    create_metadata_tables(engine)
    df1 = pd.DataFrame({"bill_id": [1], "amount": [100.0]})
    load_file(engine, df1, "cancellation_bills", "cancel/test.xlsx", logger=None)
    df2 = pd.DataFrame({"bill_id": [2], "amount": [200.0]})
    load_file(engine, df2, "cancellation_bills", "cancel/test.xlsx", logger=None)
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT operation FROM _load_metadata
            WHERE file_path = 'cancel/test.xlsx'
            ORDER BY last_loaded_at ASC
        """)).fetchall()
    ops = [r[0] for r in rows]
    assert ops[0] == "INSERT"
    assert ops[1] == "UPDATE"



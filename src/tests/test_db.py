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


def test_create_table_with_columns(engine):
    from loader.db import create_table_with_columns, get_table_columns
    create_table_with_columns(engine, "tbl_test", ["bill_id", "amount"])
    cols = get_table_columns(engine, "tbl_test")
    assert "bill_id" in cols
    assert "amount" in cols
    assert "source_file" in cols
    assert "uuid" in cols


def test_create_table_with_columns_all_text(engine):
    from loader.db import create_table_with_columns
    from sqlalchemy import inspect as sa_inspect
    create_table_with_columns(engine, "tbl_types", ["price", "note"])
    col_types = {c["name"]: str(c["type"]).upper()
                 for c in sa_inspect(engine).get_columns("tbl_types")}
    assert col_types["price"] == "TEXT"
    assert col_types["note"] == "TEXT"


def test_create_table_with_columns_idempotent(engine):
    from loader.db import create_table_with_columns
    create_table_with_columns(engine, "tbl_idem", ["col_a"])
    create_table_with_columns(engine, "tbl_idem", ["col_a"])  # must not raise


def test_create_metadata_tables_has_operation_column(engine):
    from loader.db import create_metadata_tables
    from sqlalchemy import inspect as sa_inspect
    create_metadata_tables(engine)
    cols = [c["name"] for c in sa_inspect(engine).get_columns("_load_metadata")]
    assert "operation" in cols


def test_insert_load_metadata_appends_rows(engine):
    from loader.db import create_metadata_tables, insert_load_metadata
    create_metadata_tables(engine)
    insert_load_metadata(engine, "cancel/f1.xlsx", "cancellation_bills", 100, "success", "INSERT")
    insert_load_metadata(engine, "cancel/f1.xlsx", "cancellation_bills", 102, "success", "UPDATE")
    with engine.connect() as conn:
        count = conn.execute(
            text("SELECT COUNT(*) FROM _load_metadata WHERE file_path = 'cancel/f1.xlsx'")
        ).scalar()
    assert count == 2


def test_is_file_loaded_returns_true_for_insert(engine):
    from loader.db import create_metadata_tables, insert_load_metadata, is_file_loaded
    create_metadata_tables(engine)
    insert_load_metadata(engine, "cancel/f1.xlsx", "cancellation_bills", 100, "success", "INSERT")
    assert is_file_loaded(engine, "cancel/f1.xlsx") is True


def test_is_file_loaded_returns_false_after_deleted(engine):
    from loader.db import create_metadata_tables, insert_load_metadata, is_file_loaded
    create_metadata_tables(engine)
    insert_load_metadata(engine, "cancel/f1.xlsx", "cancellation_bills", 100, "success", "INSERT")
    insert_load_metadata(engine, "cancel/f1.xlsx", "cancellation_bills", 100, "success", "DELETED")
    assert is_file_loaded(engine, "cancel/f1.xlsx") is False


def test_is_file_loaded_returns_false_for_unknown_file(engine):
    from loader.db import create_metadata_tables, is_file_loaded
    create_metadata_tables(engine)
    assert is_file_loaded(engine, "cancel/nothere.xlsx") is False


def test_is_file_loaded_backward_compat_null_operation(engine):
    """Rows from before migration (operation=NULL, status=success) must still count as loaded."""
    from loader.db import create_metadata_tables, is_file_loaded
    from datetime import datetime, timezone
    create_metadata_tables(engine)
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO _load_metadata (file_path, table_name, last_loaded_at, row_count, status)
            VALUES ('cancel/old.xlsx', 'cancellation_bills', :now, 50, 'success')
        """), {"now": datetime.now(timezone.utc)})
        conn.commit()
    assert is_file_loaded(engine, "cancel/old.xlsx") is True


def test_get_active_files_returns_inserted_files(engine):
    from loader.db import create_metadata_tables, insert_load_metadata, get_active_files
    create_metadata_tables(engine)
    insert_load_metadata(engine, "cancel/f1.xlsx", "cancellation_bills", 100, "success", "INSERT")
    insert_load_metadata(engine, "cancel/f2.xlsx", "cancellation_bills", 50, "success", "INSERT")
    active = get_active_files(engine)
    paths = {r["file_path"] for r in active}
    assert "cancel/f1.xlsx" in paths
    assert "cancel/f2.xlsx" in paths


def test_get_active_files_excludes_deleted(engine):
    from loader.db import create_metadata_tables, insert_load_metadata, get_active_files
    create_metadata_tables(engine)
    insert_load_metadata(engine, "cancel/f1.xlsx", "cancellation_bills", 100, "success", "INSERT")
    insert_load_metadata(engine, "cancel/f1.xlsx", "cancellation_bills", 100, "success", "DELETED")
    insert_load_metadata(engine, "cancel/f2.xlsx", "cancellation_bills", 50, "success", "INSERT")
    active = get_active_files(engine)
    paths = {r["file_path"] for r in active}
    assert "cancel/f1.xlsx" not in paths
    assert "cancel/f2.xlsx" in paths


def test_get_active_files_includes_updated_files(engine):
    from loader.db import create_metadata_tables, insert_load_metadata, get_active_files
    create_metadata_tables(engine)
    insert_load_metadata(engine, "cancel/f1.xlsx", "cancellation_bills", 100, "success", "INSERT")
    insert_load_metadata(engine, "cancel/f1.xlsx", "cancellation_bills", 102, "success", "UPDATE")
    active = get_active_files(engine)
    assert len([r for r in active if r["file_path"] == "cancel/f1.xlsx"]) == 1


def test_get_active_files_backward_compat_null_operation(engine):
    from loader.db import create_metadata_tables, get_active_files
    from datetime import datetime, timezone
    create_metadata_tables(engine)
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO _load_metadata (file_path, table_name, last_loaded_at, row_count, status)
            VALUES ('cancel/old.xlsx', 'cancellation_bills', :now, 50, 'success')
        """), {"now": datetime.now(timezone.utc)})
        conn.commit()
    active = get_active_files(engine)
    paths = {r["file_path"] for r in active}
    assert "cancel/old.xlsx" in paths


def test_get_active_files_excludes_failed_only_files(engine):
    """A file that only ever had failed loads must not be treated as active."""
    from loader.db import create_metadata_tables, insert_load_metadata, get_active_files
    create_metadata_tables(engine)
    insert_load_metadata(engine, "cancel/bad.xlsx", "cancellation_bills", 0, "failed", "INSERT")
    insert_load_metadata(engine, "cancel/ok.xlsx", "cancellation_bills", 100, "success", "INSERT")
    active = get_active_files(engine)
    paths = {r["file_path"] for r in active}
    assert "cancel/bad.xlsx" not in paths
    assert "cancel/ok.xlsx" in paths


def test_archive_and_delete_file_creates_deleted_table(engine):
    from loader.db import (create_metadata_tables, create_table_with_columns,
                            insert_load_metadata, archive_and_delete_file)
    from sqlalchemy import inspect as sa_inspect
    create_metadata_tables(engine)
    create_table_with_columns(engine, "cancellation_bills", ["bill_id", "amount"])
    with engine.connect() as conn:
        conn.execute(text(
            "INSERT INTO cancellation_bills (bill_id, amount, source_file) VALUES ('1', '100', 'cancel/f1.xlsx')"
        ))
        conn.commit()
    insert_load_metadata(engine, "cancel/f1.xlsx", "cancellation_bills", 1, "success", "INSERT")
    archive_and_delete_file(engine, "cancel/f1.xlsx", "cancellation_bills", logger=None)
    assert "cancellation_bills_deleted" in sa_inspect(engine).get_table_names()


def test_archive_and_delete_file_copies_rows(engine):
    from loader.db import (create_metadata_tables, create_table_with_columns,
                            insert_load_metadata, archive_and_delete_file)
    create_metadata_tables(engine)
    create_table_with_columns(engine, "cancellation_bills", ["bill_id", "amount"])
    with engine.connect() as conn:
        conn.execute(text(
            "INSERT INTO cancellation_bills (bill_id, amount, source_file) VALUES ('1', '100', 'cancel/f1.xlsx')"
        ))
        conn.execute(text(
            "INSERT INTO cancellation_bills (bill_id, amount, source_file) VALUES ('2', '200', 'cancel/f1.xlsx')"
        ))
        conn.commit()
    insert_load_metadata(engine, "cancel/f1.xlsx", "cancellation_bills", 2, "success", "INSERT")
    count = archive_and_delete_file(engine, "cancel/f1.xlsx", "cancellation_bills", logger=None)
    assert count == 2
    with engine.connect() as conn:
        archived = conn.execute(text(
            "SELECT COUNT(*) FROM cancellation_bills_deleted WHERE source_file = 'cancel/f1.xlsx'"
        )).scalar()
    assert archived == 2


def test_archive_and_delete_file_removes_from_main(engine):
    from loader.db import (create_metadata_tables, create_table_with_columns,
                            insert_load_metadata, archive_and_delete_file)
    create_metadata_tables(engine)
    create_table_with_columns(engine, "cancellation_bills", ["bill_id", "amount"])
    with engine.connect() as conn:
        conn.execute(text(
            "INSERT INTO cancellation_bills (bill_id, amount, source_file) VALUES ('1', '100', 'cancel/f1.xlsx')"
        ))
        conn.commit()
    insert_load_metadata(engine, "cancel/f1.xlsx", "cancellation_bills", 1, "success", "INSERT")
    archive_and_delete_file(engine, "cancel/f1.xlsx", "cancellation_bills", logger=None)
    with engine.connect() as conn:
        remaining = conn.execute(text(
            "SELECT COUNT(*) FROM cancellation_bills WHERE source_file = 'cancel/f1.xlsx'"
        )).scalar()
    assert remaining == 0


def test_archive_and_delete_file_logs_deleted_operation(engine):
    from loader.db import (create_metadata_tables, create_table_with_columns,
                            insert_load_metadata, archive_and_delete_file)
    create_metadata_tables(engine)
    create_table_with_columns(engine, "cancellation_bills", ["bill_id", "amount"])
    with engine.connect() as conn:
        conn.execute(text(
            "INSERT INTO cancellation_bills (bill_id, amount, source_file) VALUES ('1', '100', 'cancel/f1.xlsx')"
        ))
        conn.commit()
    insert_load_metadata(engine, "cancel/f1.xlsx", "cancellation_bills", 1, "success", "INSERT")
    archive_and_delete_file(engine, "cancel/f1.xlsx", "cancellation_bills", logger=None)
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT operation, status FROM _load_metadata
            WHERE file_path = 'cancel/f1.xlsx'
            ORDER BY last_loaded_at DESC LIMIT 1
        """)).fetchone()
    assert row[0] == "DELETED"
    assert row[1] == "success"


def test_archive_and_delete_file_deleted_table_has_deleted_at(engine):
    from loader.db import (create_metadata_tables, create_table_with_columns,
                            insert_load_metadata, archive_and_delete_file)
    from sqlalchemy import inspect as sa_inspect
    create_metadata_tables(engine)
    create_table_with_columns(engine, "cancellation_bills", ["bill_id"])
    with engine.connect() as conn:
        conn.execute(text(
            "INSERT INTO cancellation_bills (bill_id, source_file) VALUES ('1', 'cancel/f1.xlsx')"
        ))
        conn.commit()
    insert_load_metadata(engine, "cancel/f1.xlsx", "cancellation_bills", 1, "success", "INSERT")
    archive_and_delete_file(engine, "cancel/f1.xlsx", "cancellation_bills", logger=None)
    cols = [c["name"] for c in sa_inspect(engine).get_columns("cancellation_bills_deleted")]
    assert "deleted_at" in cols

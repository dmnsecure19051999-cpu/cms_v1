# File Deletion Handling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Phát hiện file bị xóa khỏi folder trong `daily` mode, archive dữ liệu sang bảng `{table}_deleted`, xóa khỏi bảng gốc, và ghi log mọi operation (INSERT / UPDATE / DELETED) vào `_load_metadata` dạng append.

**Architecture:** Thêm column `operation` vào `_load_metadata` và đổi từ upsert → append. Thêm `get_active_files()` để detect file bị xóa bằng cách so sánh DB vs disk. Thêm `archive_and_delete_file()` để thực hiện copy → delete trong một transaction. `load_file()` tự detect INSERT vs UPDATE dựa trên `is_file_loaded()`.

**Tech Stack:** Python 3.10+, SQLAlchemy 2.x, PostgreSQL (prod) / SQLite in-memory (tests), pytest

---

## File Map

| File | Thay đổi |
|------|----------|
| `src/loader/db.py` | Thêm `operation` migration, thay `upsert_load_metadata` → `insert_load_metadata`, update `is_file_loaded`, thêm `get_active_files`, `ensure_deleted_table`, `archive_and_delete_file` |
| `src/loader/loader.py` | `load_file()` tự detect INSERT/UPDATE, dùng `insert_load_metadata` |
| `main.py` | Daily mode: update error paths + thêm deleted-files block sau loop chính |
| `src/tests/test_db.py` | Thêm tests cho các function mới |
| `src/tests/test_loader.py` | Cập nhật tests dùng `load_file` |

---

## Task 1: Thêm column `operation` vào `_load_metadata`

**Files:**
- Modify: `src/loader/db.py` — `create_metadata_tables()`
- Test: `src/tests/test_db.py`

- [ ] **Step 1: Viết failing test**

Thêm vào cuối `src/tests/test_db.py`:

```python
def test_create_metadata_tables_has_operation_column(engine):
    from loader.db import create_metadata_tables
    from sqlalchemy import inspect as sa_inspect
    create_metadata_tables(engine)
    cols = [c["name"] for c in sa_inspect(engine).get_columns("_load_metadata")]
    assert "operation" in cols
```

- [ ] **Step 2: Chạy test để xác nhận fail**

```bash
.venv/bin/python -m pytest src/tests/test_db.py::test_create_metadata_tables_has_operation_column -v
```

Expected: `FAILED — AssertionError`

- [ ] **Step 3: Cập nhật `create_metadata_tables()` trong `src/loader/db.py`**

Tìm hàm `create_metadata_tables` (dòng 32–51), thêm migration sau `meta.create_all`:

```python
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
    if "operation" not in get_table_columns(engine, "_load_metadata"):
        add_column(engine, "_load_metadata", "operation", "TEXT")
```

- [ ] **Step 4: Chạy test để xác nhận pass**

```bash
.venv/bin/python -m pytest src/tests/test_db.py::test_create_metadata_tables_has_operation_column -v
```

Expected: `PASSED`

- [ ] **Step 5: Chạy toàn bộ test suite để đảm bảo không regression**

```bash
.venv/bin/python -m pytest src/tests/ -v
```

Expected: tất cả PASSED

- [ ] **Step 6: Commit**

```bash
git add src/loader/db.py src/tests/test_db.py
git commit -m "feat: add operation column migration to _load_metadata"
```

---

## Task 2: Thay `upsert_load_metadata` → `insert_load_metadata` và cập nhật `is_file_loaded`

**Files:**
- Modify: `src/loader/db.py`
- Test: `src/tests/test_db.py`

- [ ] **Step 1: Viết failing tests**

Thêm vào cuối `src/tests/test_db.py`:

```python
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
```

- [ ] **Step 2: Chạy tests để xác nhận fail**

```bash
.venv/bin/python -m pytest src/tests/test_db.py::test_insert_load_metadata_appends_rows src/tests/test_db.py::test_is_file_loaded_returns_true_for_insert src/tests/test_db.py::test_is_file_loaded_returns_false_after_deleted src/tests/test_db.py::test_is_file_loaded_returns_false_for_unknown_file src/tests/test_db.py::test_is_file_loaded_backward_compat_null_operation -v
```

Expected: tất cả FAILED

- [ ] **Step 3: Thêm `insert_load_metadata` và cập nhật `is_file_loaded` trong `src/loader/db.py`**

Tìm và **xóa** hàm `upsert_load_metadata` (dòng 134–151), **thay** bằng:

```python
def insert_load_metadata(engine: Engine, file_path: str, table_name: str,
                          row_count: int, status: str, operation: str):
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO _load_metadata (file_path, table_name, last_loaded_at, row_count, status, operation)
            VALUES (:fp, :tn, :now, :rc, :st, :op)
        """), {
            "fp": file_path,
            "tn": table_name,
            "now": datetime.now(timezone.utc),
            "rc": row_count,
            "st": status,
            "op": operation,
        })
        conn.commit()
```

Tìm và **thay** hàm `is_file_loaded` (dòng 155–160):

```python
def is_file_loaded(engine: Engine, file_path: str) -> bool:
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT operation, status FROM _load_metadata
            WHERE file_path = :fp
            ORDER BY last_loaded_at DESC
            LIMIT 1
        """), {"fp": file_path}).fetchone()
    if row is None:
        return False
    operation, status = row[0], row[1]
    return operation in ('INSERT', 'UPDATE') or (operation is None and status == STATUS_SUCCESS)
```

Cập nhật import ở đầu `src/loader/db.py` — đảm bảo `insert_load_metadata` nằm trong `__all__` nếu có, hoặc chỉ cần đổi tên là đủ (không có `__all__` trong file này).

- [ ] **Step 4: Chạy tests**

```bash
.venv/bin/python -m pytest src/tests/test_db.py -v
```

Expected: tất cả PASSED

- [ ] **Step 5: Commit**

```bash
git add src/loader/db.py src/tests/test_db.py
git commit -m "feat: replace upsert_load_metadata with append-only insert_load_metadata, update is_file_loaded"
```

---

## Task 3: Thêm `get_active_files()`

**Files:**
- Modify: `src/loader/db.py`
- Test: `src/tests/test_db.py`

- [ ] **Step 1: Viết failing test**

Thêm vào cuối `src/tests/test_db.py`:

```python
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
```

- [ ] **Step 2: Chạy tests để xác nhận fail**

```bash
.venv/bin/python -m pytest src/tests/test_db.py::test_get_active_files_returns_inserted_files src/tests/test_db.py::test_get_active_files_excludes_deleted src/tests/test_db.py::test_get_active_files_includes_updated_files src/tests/test_db.py::test_get_active_files_backward_compat_null_operation -v
```

Expected: tất cả FAILED

- [ ] **Step 3: Thêm `get_active_files()` vào `src/loader/db.py`**

Thêm sau hàm `is_file_loaded`:

```python
def get_active_files(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT file_path, table_name FROM (
                SELECT file_path, table_name, operation, status,
                       ROW_NUMBER() OVER (
                           PARTITION BY file_path ORDER BY last_loaded_at DESC
                       ) AS rn
                FROM _load_metadata
            ) t
            WHERE rn = 1
              AND (operation IN ('INSERT', 'UPDATE')
                   OR (operation IS NULL AND status = 'success'))
        """)).fetchall()
    return [{"file_path": r[0], "table_name": r[1]} for r in rows]
```

- [ ] **Step 4: Chạy tests**

```bash
.venv/bin/python -m pytest src/tests/test_db.py -v
```

Expected: tất cả PASSED

- [ ] **Step 5: Commit**

```bash
git add src/loader/db.py src/tests/test_db.py
git commit -m "feat: add get_active_files to detect files currently loaded in DB"
```

---

## Task 4: Thêm `ensure_deleted_table()` và `archive_and_delete_file()`

**Files:**
- Modify: `src/loader/db.py`
- Test: `src/tests/test_db.py`

- [ ] **Step 1: Viết failing tests**

Thêm vào cuối `src/tests/test_db.py`:

```python
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
```

- [ ] **Step 2: Chạy tests để xác nhận fail**

```bash
.venv/bin/python -m pytest src/tests/test_db.py::test_archive_and_delete_file_creates_deleted_table src/tests/test_db.py::test_archive_and_delete_file_copies_rows src/tests/test_db.py::test_archive_and_delete_file_removes_from_main src/tests/test_db.py::test_archive_and_delete_file_logs_deleted_operation src/tests/test_db.py::test_archive_and_delete_file_deleted_table_has_deleted_at -v
```

Expected: tất cả FAILED

- [ ] **Step 3: Thêm `ensure_deleted_table()` và `archive_and_delete_file()` vào `src/loader/db.py`**

Thêm sau hàm `get_active_files`:

```python
def ensure_deleted_table(engine: Engine, table_name: str):
    deleted_table = f"{table_name}_deleted"
    insp = sa_inspect(engine)
    if not insp.has_table(deleted_table):
        with engine.connect() as conn:
            conn.execute(text(
                f'CREATE TABLE "{deleted_table}" AS '
                f'SELECT * FROM "{table_name}" WHERE 1=0'
            ))
            conn.commit()
        add_column(engine, deleted_table, "deleted_at", "TIMESTAMP")
    else:
        main_cols = set(get_table_columns(engine, table_name))
        deleted_cols = set(get_table_columns(engine, deleted_table))
        for col in main_cols:
            if col not in deleted_cols:
                add_column(engine, deleted_table, col, "TEXT")


def archive_and_delete_file(engine: Engine, file_path: str, table_name: str,
                             logger=None) -> int:
    deleted_table = f"{table_name}_deleted"
    try:
        ensure_deleted_table(engine, table_name)

        main_cols = get_table_columns(engine, table_name)
        cols_sql = ", ".join(f'"{c}"' for c in main_cols)

        with engine.connect() as conn:
            row_count = conn.execute(text(
                f'SELECT COUNT(*) FROM "{table_name}" WHERE source_file = :fp'
            ), {"fp": file_path}).scalar() or 0

            conn.execute(text(
                f'INSERT INTO "{deleted_table}" ({cols_sql}, "deleted_at") '
                f'SELECT {cols_sql}, CURRENT_TIMESTAMP '
                f'FROM "{table_name}" WHERE source_file = :fp'
            ), {"fp": file_path})

            conn.execute(text(
                f'DELETE FROM "{table_name}" WHERE source_file = :fp'
            ), {"fp": file_path})
            conn.commit()

        insert_load_metadata(engine, file_path, table_name, row_count, "success", "DELETED")
        if logger:
            logger.info(f"DELETED — {file_path} — {row_count} rows archived to {deleted_table}")
        return row_count

    except Exception as e:
        insert_load_metadata(engine, file_path, table_name, 0, "failed", "DELETED")
        if logger:
            logger.error(f"DELETE_FAILED — {file_path} — {e}")
        raise
```

Cập nhật import ở đầu `src/loader/db.py`: thêm `sa_inspect as sa_inspect` vào dòng import `inspect as sa_inspect` (đã có trong file).

- [ ] **Step 4: Chạy tests**

```bash
.venv/bin/python -m pytest src/tests/test_db.py -v
```

Expected: tất cả PASSED

- [ ] **Step 5: Commit**

```bash
git add src/loader/db.py src/tests/test_db.py
git commit -m "feat: add ensure_deleted_table and archive_and_delete_file"
```

---

## Task 5: Cập nhật `load_file()` để dùng `insert_load_metadata` với operation detection

**Files:**
- Modify: `src/loader/loader.py`
- Test: `src/tests/test_loader.py`

- [ ] **Step 1: Viết failing tests**

Thêm vào cuối `src/tests/test_loader.py`:

```python
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
```

- [ ] **Step 2: Chạy tests để xác nhận fail**

```bash
.venv/bin/python -m pytest src/tests/test_loader.py::test_load_file_logs_insert_operation src/tests/test_loader.py::test_load_file_logs_update_operation_on_reload -v
```

Expected: FAILED (NameError hoặc AttributeError vì `upsert_load_metadata` chưa được thay)

- [ ] **Step 3: Cập nhật `src/loader/loader.py`**

Ở đầu file, thay import:
```python
from loader.db import (
    add_column,
    create_table_with_columns,
    get_table_columns,
    is_file_loaded,
    upsert_load_metadata,
    _uuid_col_def,
)
```
thành:
```python
from loader.db import (
    add_column,
    create_table_with_columns,
    get_table_columns,
    is_file_loaded,
    insert_load_metadata,
    _uuid_col_def,
)
```

Trong hàm `load_file` (dòng 105–183), tìm đoạn:
```python
    if is_file_loaded(engine, rel_path):
        with engine.connect() as conn:
            conn.execute(
                text(f'DELETE FROM "{table_name}" WHERE source_file = :fp'),
                {"fp": rel_path},
            )
            conn.commit()
```

Thay bằng:
```python
    already_loaded = is_file_loaded(engine, rel_path)
    operation = "UPDATE" if already_loaded else "INSERT"
    if already_loaded:
        with engine.connect() as conn:
            conn.execute(
                text(f'DELETE FROM "{table_name}" WHERE source_file = :fp'),
                {"fp": rel_path},
            )
            conn.commit()
```

Cuối hàm `load_file`, tìm dòng:
```python
    status = "success" if skipped == 0 else "partial"
    upsert_load_metadata(engine, rel_path, table_name, loaded, status)
    return {"loaded": loaded, "skipped": skipped}
```

Thay bằng:
```python
    status = "success" if skipped == 0 else "partial"
    insert_load_metadata(engine, rel_path, table_name, loaded, status, operation)
    return {"loaded": loaded, "skipped": skipped}
```

- [ ] **Step 4: Chạy toàn bộ test suite**

```bash
.venv/bin/python -m pytest src/tests/ -v
```

Expected: tất cả PASSED

- [ ] **Step 5: Commit**

```bash
git add src/loader/loader.py src/tests/test_loader.py
git commit -m "feat: load_file detects INSERT vs UPDATE operation, logs via insert_load_metadata"
```

---

## Task 6: Cập nhật `main.py` — error paths + deleted-files detection trong daily mode

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Cập nhật imports trong `main.py`**

Tìm dòng import:
```python
from loader.db import (get_engine, ensure_database, create_metadata_tables,
                        get_last_run_time, insert_run_log, finish_run_log,
                        upsert_load_metadata, get_table_columns, drop_table,
                        upgrade_column_types)
```

Thay bằng:
```python
from loader.db import (get_engine, ensure_database, create_metadata_tables,
                        get_last_run_time, insert_run_log, finish_run_log,
                        insert_load_metadata, get_table_columns, drop_table,
                        upgrade_column_types, get_active_files,
                        archive_and_delete_file)
```

- [ ] **Step 2: Thêm biến `deleted` vào `run()` và cập nhật `init` mode**

Tìm dòng:
```python
    processed = skipped = errors = 0
```
Thay bằng:
```python
    processed = skipped = errors = deleted = 0
```

Trong `init` mode, hàm `load_one` — tìm dòng:
```python
                    upsert_load_metadata(engine, rel, table, 0, "failed")
```
(xuất hiện 2 lần trong `load_one`). Thay **cả hai** bằng:
```python
                    insert_load_metadata(engine, rel, table, 0, "failed", "INSERT")
```

- [ ] **Step 3: Cập nhật `daily` mode — error paths**

Trong `daily` mode, tìm dòng:
```python
                upsert_load_metadata(engine, rel, table, 0, "failed")
```
(xuất hiện 2 lần: SKIP_FILE và ERROR). Thay **cả hai** bằng:
```python
                op = "UPDATE" if is_file_loaded(engine, rel) else "INSERT"
                insert_load_metadata(engine, rel, table, 0, "failed", op)
```

Đảm bảo import `is_file_loaded` đã có trong imports ở trên — thêm vào dòng import nếu chưa có:
```python
from loader.db import (get_engine, ensure_database, create_metadata_tables,
                        get_last_run_time, insert_run_log, finish_run_log,
                        insert_load_metadata, get_table_columns, drop_table,
                        upgrade_column_types, get_active_files,
                        archive_and_delete_file, is_file_loaded)
```

- [ ] **Step 4: Thêm deleted-files detection block vào `daily` mode**

Trong `daily` mode, sau vòng `for idx, f in enumerate(files, 1)` (tức là sau dòng `if new_cols_by_table: ...` và trước `finally:`), thêm block sau:

```python
        # Detect and archive deleted files
        logger.info("DAILY — checking for deleted files")
        folder_name_map = {Path(folder).name: folder for folder in cfg.folder_map}
        active_files = get_active_files(engine)
        for active in active_files:
            rel = active["file_path"]
            table = active["table_name"]
            parts = Path(rel).parts
            if not parts:
                continue
            abs_folder = folder_name_map.get(parts[0])
            if abs_folder is None:
                continue
            abs_path = Path(abs_folder).joinpath(*parts[1:])
            if not abs_path.exists():
                try:
                    n = archive_and_delete_file(engine, rel, table, logger)
                    deleted += 1
                except Exception as e:
                    errors += 1
                    logger.error(f"DELETE_FAILED — {rel} — {e}")
```

- [ ] **Step 5: Cập nhật `finish_run_log` và log summary**

Tìm dòng trong `finally`:
```python
        finish_run_log(engine, run_id, processed, skipped, errors)
        logger.info(f"Run finished — {processed} loaded, {skipped} skipped, {errors} errors")
```
Thay bằng:
```python
        finish_run_log(engine, run_id, processed, skipped, errors)
        logger.info(f"Run finished — {processed} loaded, {skipped} skipped, {errors} errors, {deleted} deleted")
```

- [ ] **Step 6: Chạy toàn bộ test suite**

```bash
.venv/bin/python -m pytest src/tests/ -v
```

Expected: tất cả PASSED

- [ ] **Step 7: Commit**

```bash
git add main.py
git commit -m "feat: daily mode detects deleted files and archives them to _deleted tables"
```

---

## Kiểm tra thủ công (manual smoke test)

Sau khi tất cả tasks hoàn thành:

- [ ] **Chạy init mode với sample data**

```bash
.venv/bin/python main.py --mode init
```

Kiểm tra `_load_metadata`: tất cả rows phải có `operation = 'INSERT'`.

- [ ] **Xóa một file khỏi folder, chạy daily mode**

```bash
# Xóa bất kỳ file nào trong CANCEL_DIR hoặc CUSTOMER_DATA_DIR
# (đây là thao tác test — backup file trước nếu cần)
.venv/bin/python main.py --mode daily
```

Kiểm tra:
1. Log có dòng `DELETED — <file_path> — N rows archived to <table>_deleted`
2. Bảng `<table>_deleted` tồn tại và có dữ liệu
3. `_load_metadata` có row mới với `operation = 'DELETED'`
4. Bảng gốc không còn rows của file đó (`SELECT COUNT(*) FROM <table> WHERE source_file = '<rel_path>'` → 0)

- [ ] **Chạy lại daily mode (không xóa thêm file nào)**

```bash
.venv/bin/python main.py --mode daily
```

Log phải không có thêm dòng DELETED nào — file đã xóa không bị xử lý lại.

# TEXT-first Load + Post-init Type Upgrade Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Eliminate datatype errors during `init` by loading all columns as TEXT first, then upgrading column types from actual DB data after the full load completes.

**Architecture:** Remove all pandas-based type inference from the load path. `_ensure_table_schema` always creates TEXT columns. A new `upgrade_column_types()` function in `db.py` runs after init, attempting `ALTER COLUMN TYPE FLOAT` then `TIMESTAMP` per column using PostgreSQL's `USING` cast — keeping TEXT for any column that fails.

**Tech Stack:** Python 3.10+, SQLAlchemy, PostgreSQL (`psycopg2`), pytest, SQLite (tests)

---

## Context for implementer

The current code in `loader/loader.py` has `_ensure_table_schema` using `infer_sql_type` (from `excel_reader.py`) to decide column types at table creation time. This causes INSERT failures when pandas infers FLOAT but actual cell values contain "N/A", "—", or inconsistent date formats.

`loader/main.py` `init` mode currently calls `pre_create_table_schema` (a separate pre-scan pass) before loading. Both of these are being removed.

**After these changes:**
- `init`: creates TEXT tables → loads all rows cleanly → upgrades types in-place
- `daily`: unchanged — inserts into already-typed schema

---

### Task 1: Add `upgrade_column_types` to `db.py` (TDD)

**Files:**
- Modify: `tests/test_db.py`
- Modify: `loader/db.py`

**Step 1: Write the failing test**

Add to `tests/test_db.py`:

```python
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
    """source_file column must never be upgraded."""
    from loader.db import upgrade_column_types, get_table_columns
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE upg_tbl2 (source_file TEXT)"))
        conn.commit()
    upgrade_column_types(engine, "upg_tbl2", logger=None)
    assert "source_file" in get_table_columns(engine, "upg_tbl2")
```

**Step 2: Run to verify FAIL**

```bash
.venv/bin/python -m pytest tests/test_db.py::test_upgrade_column_types_noop_on_non_postgres tests/test_db.py::test_upgrade_column_types_skips_source_file -v
```

Expected: `ImportError: cannot import name 'upgrade_column_types'`

**Step 3: Implement `upgrade_column_types` in `loader/db.py`**

Add after `drop_table`:

```python
def upgrade_column_types(engine: Engine, table_name: str, logger=None):
    skip_cols = {"source_file"}
    cols = get_table_columns(engine, table_name)
    for col in cols:
        if col in skip_cols:
            continue
        for sql_type, cast_expr in [
            ("FLOAT", f'"{col}"::FLOAT'),
            ("TIMESTAMP", f'"{col}"::TIMESTAMP'),
        ]:
            try:
                with engine.connect() as conn:
                    conn.execute(text(
                        f'ALTER TABLE "{table_name}" '
                        f'ALTER COLUMN "{col}" TYPE {sql_type} '
                        f'USING {cast_expr}'
                    ))
                    conn.commit()
                if logger:
                    logger.info(f"TYPE_UPGRADE — {table_name}.{col} → {sql_type}")
                break
            except Exception:
                pass
```

**Step 4: Run tests to verify PASS**

```bash
.venv/bin/python -m pytest tests/test_db.py -v
```

Expected: all PASS

**Step 5: Commit**

```bash
git add loader/db.py tests/test_db.py
git commit -m "feat: add upgrade_column_types to db.py"
```

---

### Task 2: Update `_ensure_table_schema` to use TEXT only (TDD)

**Files:**
- Modify: `tests/test_loader.py`
- Modify: `loader/loader.py`

**Step 1: Update existing test + add new test**

In `tests/test_loader.py`, replace the test `test_pre_create_table_schema_creates_table` block with:

```python
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
```

Also remove these tests entirely (they test functions being deleted):
- `test_pre_create_table_schema_creates_table`
- `test_pre_create_table_schema_union_of_columns`
- `test_pre_create_table_schema_adds_missing_cols_to_existing`
- `test_infer_group_schema_uses_all_files`
- `test_pre_create_table_schema_conflicting_types_fallback_to_text`

**Step 2: Run to verify FAIL**

```bash
.venv/bin/python -m pytest tests/test_loader.py::test_ensure_schema_creates_all_text_columns -v
```

Expected: FAIL — columns are currently created with inferred types, not TEXT.

**Step 3: Update `_ensure_table_schema` in `loader/loader.py`**

Change the `if not existing:` block inside `_ensure_table_schema`. Remove the `from loader.excel_reader import infer_sql_type` import and replace the column type logic:

Old:
```python
def _ensure_table_schema(engine: Engine, df: pd.DataFrame, table_name: str, logger):
    from loader.db import get_table_columns, add_column
    from loader.excel_reader import infer_sql_type

    existing = get_table_columns(engine, table_name)
    if not existing:
        cols_sql = ", ".join(
            f'"{_safe_col(c)}" {infer_sql_type(df[c])} NULL' for c in df.columns
        ) + ', "source_file" TEXT NULL'
```

New:
```python
def _ensure_table_schema(engine: Engine, df: pd.DataFrame, table_name: str, logger):
    from loader.db import get_table_columns, add_column

    existing = get_table_columns(engine, table_name)
    if not existing:
        cols_sql = ", ".join(
            f'"{_safe_col(c)}" TEXT NULL' for c in df.columns
        ) + ', "source_file" TEXT NULL'
```

**Step 4: Run tests to verify PASS**

```bash
.venv/bin/python -m pytest tests/test_loader.py -v
```

Expected: all PASS

**Step 5: Commit**

```bash
git add loader/loader.py tests/test_loader.py
git commit -m "feat: create all columns as TEXT in _ensure_table_schema"
```

---

### Task 3: Remove `infer_group_schema` and `pre_create_table_schema` from `loader/loader.py`

**Files:**
- Modify: `loader/loader.py`

No new tests needed — tests for these functions were already removed in Task 2.

**Step 1: Delete the two functions from `loader/loader.py`**

Remove entirely:
- `_merge_sql_types` (helper used only by `infer_group_schema`)
- `infer_group_schema`
- `pre_create_table_schema`

**Step 2: Run full test suite**

```bash
.venv/bin/python -m pytest tests/ -v
```

Expected: all PASS (no tests reference these functions anymore)

**Step 3: Commit**

```bash
git add loader/loader.py
git commit -m "refactor: remove pre_create_table_schema and infer_group_schema"
```

---

### Task 4: Remove `infer_sql_type` from `loader/excel_reader.py` (TDD)

**Files:**
- Modify: `tests/test_excel_reader.py`
- Modify: `loader/excel_reader.py`

**Step 1: Remove `test_infer_sql_type` from `tests/test_excel_reader.py`**

Delete this test:

```python
def test_infer_sql_type():
    from loader.excel_reader import infer_sql_type
    assert infer_sql_type(pd.Series([1.0, 2.0])) == "FLOAT"
    assert infer_sql_type(pd.Series(pd.to_datetime(["2025-01-01"]))) == "TIMESTAMP"
    assert infer_sql_type(pd.Series(["a", "b"])) == "TEXT"
```

**Step 2: Run to verify remaining tests still pass**

```bash
.venv/bin/python -m pytest tests/test_excel_reader.py -v
```

Expected: all PASS

**Step 3: Remove `infer_sql_type` from `loader/excel_reader.py`**

Delete the function:

```python
def infer_sql_type(series: pd.Series) -> str:
    if pd.api.types.is_datetime64_any_dtype(series):
        return "TIMESTAMP"
    if pd.api.types.is_numeric_dtype(series):
        return "FLOAT"
    return "TEXT"
```

**Step 4: Run full test suite**

```bash
.venv/bin/python -m pytest tests/ -v
```

Expected: all PASS

**Step 5: Commit**

```bash
git add loader/excel_reader.py tests/test_excel_reader.py
git commit -m "refactor: remove infer_sql_type from excel_reader"
```

---

### Task 5: Update `main.py` init mode to call `upgrade_column_types`

**Files:**
- Modify: `loader/main.py`

**Step 1: Update imports in `loader/main.py`**

Old import line:
```python
from loader.db import (get_engine, ensure_database, create_metadata_tables,
                        get_last_run_time, insert_run_log, finish_run_log,
                        upsert_load_metadata, get_table_columns, drop_table)
```

New:
```python
from loader.db import (get_engine, ensure_database, create_metadata_tables,
                        get_last_run_time, insert_run_log, finish_run_log,
                        upsert_load_metadata, get_table_columns, drop_table,
                        upgrade_column_types)
```

Old loader import:
```python
from loader.loader import load_file, pre_create_table_schema
```

New:
```python
from loader.loader import load_file
```

**Step 2: Replace the `init` pre-schema block with `drop_table` only**

Find this block in `run()`:

```python
    if mode == "init":
        from collections import defaultdict
        table_buckets: dict = defaultdict(list)
        for f in files:
            table_buckets[f["table_name"]].append(f)
        logger.info("INIT — dropping existing tables and rebuilding schemas from all files")
        for table_name, tfiles in table_buckets.items():
            drop_table(engine, table_name)
            header = cfg.table_header_map.get(table_name, 0)
            pre_create_table_schema(engine, tfiles, table_name, header, logger)
```

Replace with:

```python
    if mode == "init":
        from collections import defaultdict
        table_buckets: dict = defaultdict(list)
        for f in files:
            table_buckets[f["table_name"]].append(f)
        logger.info("INIT — dropping existing tables")
        for table_name in table_buckets:
            drop_table(engine, table_name)
```

**Step 3: Add `upgrade_column_types` call after the load loop**

Find the `finally:` block:

```python
    finally:
        finish_run_log(engine, run_id, processed, skipped, errors)
        logger.info(f"Run finished — {processed} loaded, {skipped} skipped, {errors} errors")
```

Add the upgrade call just before `finally:`:

```python
    if mode == "init":
        logger.info("INIT — upgrading column types from actual data")
        for table_name in set(f["table_name"] for f in files):
            upgrade_column_types(engine, table_name, logger)

    finally:
        finish_run_log(engine, run_id, processed, skipped, errors)
        logger.info(f"Run finished — {processed} loaded, {skipped} skipped, {errors} errors")
```

**Step 4: Run full test suite**

```bash
.venv/bin/python -m pytest tests/ -v
```

Expected: all PASS

**Step 5: Commit**

```bash
git add loader/main.py
git commit -m "feat: init mode uses TEXT-first load then upgrade_column_types"
```

---

### Task 6: Also remove `table_header_map` usage from `config.py` that was only used by `pre_create_table_schema`

Wait — `table_header_map` is still used in `main.py` for `header` param passed to `read_excel`. Keep it.

No changes needed. Skip this task.

---

## Verification

After all tasks, run:

```bash
.venv/bin/python -m pytest tests/ -v
```

All tests must pass. Then test with real data:

```bash
.venv/bin/python -m loader.main --mode test
```

Check logs for `TYPE_UPGRADE` lines confirming columns were upgraded after load.

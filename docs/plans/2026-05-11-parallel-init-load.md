# Parallel Init Load Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Speed up `init` mode by (1) replacing row-by-row INSERT with bulk executemany and (2) loading files concurrently with `ThreadPoolExecutor(max_workers=3)`.

**Architecture:** Three phases in `init` only — Phase 1 reads headers to build complete table schemas (sequential, DDL-safe); Phase 2 bulk-inserts all files in parallel with 3 workers (no DDL, thread-safe); Phase 3 runs `upgrade_column_types` sequentially as before. `daily` mode is untouched except it also benefits from bulk insert.

**Tech Stack:** Python `concurrent.futures.ThreadPoolExecutor`, SQLAlchemy `executemany` via `text()`, `pandas.read_excel(nrows=0)` for header-only reads.

---

### Task 1: Add `create_table_with_columns()` to db.py

**Files:**
- Modify: `src/loader/db.py`
- Test: `src/tests/test_db.py`

**Step 1: Write the failing test**

Add to `src/tests/test_db.py`:

```python
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
    assert "TEXT" in col_types["price"]
    assert "TEXT" in col_types["note"]
```

**Step 2: Run test to verify it fails**

```bash
.venv/bin/python -m pytest src/tests/test_db.py::test_create_table_with_columns -v
```
Expected: `FAILED` — `ImportError: cannot import name 'create_table_with_columns'`

**Step 3: Implement in `src/loader/db.py`**

Add after the `drop_table` function (around line 73):

```python
def create_table_with_columns(engine: Engine, table_name: str, columns: list[str]):
    if engine.dialect.name == "postgresql":
        uuid_def = '"uuid" UUID PRIMARY KEY DEFAULT gen_random_uuid()'
    else:
        uuid_def = '"uuid" TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16))))'
    col_defs = ", ".join(f'"{c}" TEXT NULL' for c in columns)
    ddl = f'CREATE TABLE "{table_name}" ({uuid_def}, {col_defs}, "source_file" TEXT NULL)'
    with engine.connect() as conn:
        conn.execute(text(ddl))
        conn.commit()
```

**Step 4: Run tests to verify they pass**

```bash
.venv/bin/python -m pytest src/tests/test_db.py -v
```
Expected: all PASS

**Step 5: Commit**

```bash
git add src/loader/db.py src/tests/test_db.py
git commit -m "feat: add create_table_with_columns helper to db"
```

---

### Task 2: Add `build_table_schemas()` to loader.py

This function reads column headers from all files (no data), builds the union schema per table, and creates all tables. Files that fail to open are returned as skipped so Phase 2 never retries them.

**Files:**
- Modify: `src/loader/loader.py`
- Test: `src/tests/test_loader.py`

**Step 1: Write the failing test**

Add to `src/tests/test_loader.py`:

```python
import tempfile
import os


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

        import logging
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
```

**Step 2: Run test to verify it fails**

```bash
.venv/bin/python -m pytest src/tests/test_loader.py::test_build_table_schemas_creates_tables -v
```
Expected: `FAILED` — `ImportError: cannot import name 'build_table_schemas'`

**Step 3: Implement in `src/loader/loader.py`**

Add these imports at the top:

```python
from collections import defaultdict
import pandas as pd  # already imported
```

Add the function before `load_file`:

```python
def build_table_schemas(engine, files: list[dict], cfg, logger) -> tuple[list[dict], int]:
    """Phase 1: read column headers only, create all tables with union schema.

    Returns (files_to_load, n_skipped) — files_to_load excludes unreadable files.
    """
    from loader.db import create_table_with_columns, upsert_load_metadata

    cols_by_table: dict[str, set[str]] = defaultdict(set)
    files_to_load = []
    n_skipped = 0

    for f in files:
        path = f["file_path"]
        rel = f["rel_path"]
        table = f["table_name"]
        header = cfg.table_header_map.get(table, 0)
        try:
            header_df = pd.read_excel(path, header=header, nrows=0)
            norm_cols = [normalize_col_name(c) for c in header_df.columns]
            cols_by_table[table].update(norm_cols)
            files_to_load.append(f)
        except Exception as e:
            if logger:
                logger.warning(f"SKIP_FILE — {rel} — cannot read headers: {e}")
            upsert_load_metadata(engine, rel, table, 0, "failed")
            n_skipped += 1

    for table_name, cols in cols_by_table.items():
        create_table_with_columns(engine, table_name, sorted(cols))
        if logger:
            logger.info(f"SCHEMA — {table_name} — {len(cols)} columns")

    return files_to_load, n_skipped
```

**Step 4: Run tests to verify they pass**

```bash
.venv/bin/python -m pytest src/tests/test_loader.py -v
```
Expected: all PASS

**Step 5: Commit**

```bash
git add src/loader/loader.py src/tests/test_loader.py
git commit -m "feat: add build_table_schemas for phase-1 schema build"
```

---

### Task 3: Rewrite `load_file()` with bulk insert + chunk fallback

Replace the row-by-row INSERT loop with chunked `executemany`. Each chunk of 500 rows is inserted in one transaction. If the bulk fails, fall back to row-by-row for that chunk so `SKIP_ROW` behavior is preserved.

**Files:**
- Modify: `src/loader/loader.py`
- Test: `src/tests/test_loader.py`

**Step 1: Write the new test (large file hits bulk path)**

Add to `src/tests/test_loader.py`:

```python
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
```

**Step 2: Run test to verify it passes already (it should — just verifying baseline)**

```bash
.venv/bin/python -m pytest src/tests/test_loader.py::test_load_large_file_bulk -v
```

Note the run time. After Task 3 it should be noticeably faster for large DataFrames.

**Step 3: Rewrite the row loop in `load_file()`**

Replace the entire section from `loaded = 0` to the end of `load_file` (currently lines 94–119) with:

```python
    df = df.copy()
    df.columns = [normalize_col_name(c) for c in df.columns]
    df["source_file"] = rel_path

    col_info = inspect(engine).get_columns(table_name)
    col_sa_types = {c["name"]: c["type"] for c in col_info}
    existing_cols = list(col_sa_types)
    df = df[[c for c in df.columns if c in existing_cols]]

    col_keys = list(df.columns)
    cols_sql = ", ".join(f'"{_safe_col(c)}"' for c in col_keys)
    params_sql = ", ".join(f":p{i}" for i in range(len(col_keys)))
    stmt = text(f'INSERT INTO "{table_name}" ({cols_sql}) VALUES ({params_sql})')

    loaded = 0
    skipped = 0
    chunk_size = 500

    for chunk_start in range(0, len(df), chunk_size):
        chunk = df.iloc[chunk_start : chunk_start + chunk_size]

        # Build param dicts, catching per-row coercion errors immediately
        good_records: list[tuple[int, dict]] = []
        for idx, row in chunk.iterrows():
            try:
                record = {
                    f"p{i}": _coerce_value(v, col_sa_types.get(_safe_col(k)))
                    for i, (k, v) in enumerate(row.items())
                }
                good_records.append((idx, record))
            except Exception as e:
                skipped += 1
                if logger:
                    logger.warning(f"SKIP_ROW — {rel_path} — row {idx} — {e}")

        if not good_records:
            continue

        # Attempt bulk insert for this chunk
        try:
            param_list = [r for _, r in good_records]
            with engine.connect() as conn:
                conn.execute(stmt, param_list)
                conn.commit()
            loaded += len(good_records)
        except Exception:
            # Fallback: row-by-row so individual bad rows are skipped
            for idx, record in good_records:
                try:
                    with engine.connect() as conn:
                        conn.execute(stmt, record)
                        conn.commit()
                    loaded += 1
                except Exception as e:
                    skipped += 1
                    if logger:
                        logger.warning(f"SKIP_ROW — {rel_path} — row {idx} — {e}")

    status = "success" if skipped == 0 else "partial"
    upsert_load_metadata(engine, rel_path, table_name, loaded, status)
    return {"loaded": loaded, "skipped": skipped}
```

**Step 4: Run all loader tests**

```bash
.venv/bin/python -m pytest src/tests/test_loader.py -v
```
Expected: all PASS — `test_skip_row_on_bad_data` must still pass (coercion error hits the per-row catch before bulk attempt).

**Step 5: Run the full test suite**

```bash
.venv/bin/python -m pytest src/tests/ -v
```
Expected: all PASS

**Step 6: Commit**

```bash
git add src/loader/loader.py src/tests/test_loader.py
git commit -m "feat: replace row-by-row INSERT with chunked bulk executemany"
```

---

### Task 4: Refactor `main.py` init branch into 3-phase pipeline

Wire up Phase 1 (`build_table_schemas`) and Phase 2 (`ThreadPoolExecutor`) for `init` mode. `daily` mode is untouched.

**Files:**
- Modify: `main.py`

**Step 1: Add imports at the top of `main.py`** (after existing imports)

```python
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
```

**Step 2: Replace the `init` branch in `run()`**

The current `run()` function has:
1. Lines 41–57: drop tables + scan files (for init) / scan changed files (for daily)
2. Lines 60–114: the main loop + upgrade

Replace the **entire body of `run()`** with the following. `daily` mode inner loop is identical to today's; only `init` changes.

```python
def run(mode: str):
    cfg = Config()
    start_time = datetime.now(tz=timezone.utc)
    run_id_str = start_time.strftime("%Y%m%d_%H%M%S")
    logger = setup_logger(log_dir="logs", run_id=run_id_str)

    try:
        ensure_database(cfg.db_url)
        engine = get_engine(cfg.db_url, pool_size=5)
        create_metadata_tables(engine)
    except Exception as e:
        logger.critical(f"DB bootstrap failed: {e}")
        raise

    run_id = insert_run_log(engine, mode, start_time)
    logger.info(f"Run started — mode={mode} run_id={run_id}")

    processed = skipped = errors = 0
    loaded_tables: set[str] = set()
    new_cols_by_table: dict[str, set[str]] = defaultdict(set)

    try:
        if mode == "init":
            all_files = scan_all_files(cfg.folder_map)
            logger.info(f"Scanning: {len(all_files)} files found")

            # Drop existing tables
            table_names = {f["table_name"] for f in all_files}
            logger.info("INIT — dropping existing tables")
            for table_name in table_names:
                drop_table(engine, table_name)

            # Phase 1: build schemas from headers
            logger.info("INIT — Phase 1: building table schemas from file headers")
            files_to_load, n_skipped = build_table_schemas(engine, all_files, cfg, logger)
            skipped += n_skipped

            # Phase 2: parallel bulk load
            total = len(files_to_load)
            logger.info(f"INIT — Phase 2: loading {total} files (3 workers)")

            counter_lock = threading.Lock()
            completed_count = 0
            load_stats: dict[str, dict] = {}   # rel_path -> stats

            def load_one(f: dict) -> dict:
                path = f["file_path"]
                rel = f["rel_path"]
                table = f["table_name"]
                header = cfg.table_header_map.get(table, 0)
                df, read_err = read_excel(path, header=header)
                if read_err:
                    logger.warning(f"SKIP_FILE — {rel} — cannot read: {read_err}")
                    upsert_load_metadata(engine, rel, table, 0, "failed")
                    return {"rel": rel, "table": table, "outcome": "skip"}
                try:
                    stats = load_file(engine, df, table, rel, logger)
                    logger.info(f"LOADED — {rel} — {stats['loaded']} rows ({stats['skipped']} skipped)")
                    return {"rel": rel, "table": table, "outcome": "ok", "stats": stats}
                except Exception as e:
                    logger.error(f"ERROR — {rel} — {e}")
                    upsert_load_metadata(engine, rel, table, 0, "failed")
                    return {"rel": rel, "table": table, "outcome": "error"}

            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = {executor.submit(load_one, f): f for f in files_to_load}
                for future in as_completed(futures):
                    result = future.result()
                    with counter_lock:
                        completed_count += 1
                        pct = completed_count * 100 // total if total else 100
                    logger.info(f"PROGRESS — {completed_count}/{total} ({pct}%)")
                    if result["outcome"] == "ok":
                        processed += 1
                        loaded_tables.add(result["table"])
                    elif result["outcome"] == "skip":
                        skipped += 1
                    else:
                        errors += 1

            # Phase 3: upgrade column types
            logger.info("INIT — Phase 3: upgrading column types")
            for table_name in loaded_tables:
                upgrade_column_types(engine, table_name, logger)

        else:  # daily
            last_run = get_last_run_time(engine)
            if last_run is None:
                logger.info("No previous run found, scanning all files")
                files = scan_all_files(cfg.folder_map)
            else:
                if last_run.tzinfo is None:
                    last_run = last_run.replace(tzinfo=timezone.utc)
                files = scan_changed_files(cfg.folder_map, last_run)

            logger.info(f"Scanning: {len(files)} files to process")
            total = len(files)

            for idx, f in enumerate(files, 1):
                path = f["file_path"]
                rel = f["rel_path"]
                table = f["table_name"]
                header = cfg.table_header_map.get(table, 0)
                df, read_err = read_excel(path, header=header)
                if read_err:
                    logger.warning(f"SKIP_FILE — {rel} — cannot read: {read_err}")
                    upsert_load_metadata(engine, rel, table, 0, "failed")
                    skipped += 1
                    logger.info(f"PROGRESS — {idx}/{total} ({idx*100//total}%)")
                    continue

                existing = get_table_columns(engine, table)
                norm_df_cols = {normalize_col_name(c) for c in df.columns}
                schema_cols = [c for c in existing if c not in ("source_file", "uuid")]
                missing = [c for c in schema_cols if c not in norm_df_cols]
                if missing:
                    logger.info(f"MISSING_COLS — {rel} — {missing} will be NULL")

                new_cols = [c for c in norm_df_cols if c not in existing]

                try:
                    stats = load_file(engine, df, table, rel, logger)
                    processed += 1
                    loaded_tables.add(table)
                    if new_cols:
                        new_cols_by_table[table].update(new_cols)
                    logger.info(f"LOADED — {rel} — {stats['loaded']} rows ({stats['skipped']} skipped)")
                except Exception as e:
                    errors += 1
                    logger.error(f"ERROR — {rel} — {e}")
                    upsert_load_metadata(engine, rel, table, 0, "failed")

                logger.info(f"PROGRESS — {idx}/{total} ({idx*100//total}%)")

            if new_cols_by_table:
                logger.info("DAILY — upgrading column types for new columns")
                for table_name, cols in new_cols_by_table.items():
                    upgrade_column_types(engine, table_name, logger, cols=list(cols))

    finally:
        finish_run_log(engine, run_id, processed, skipped, errors)
        logger.info(f"Run finished — {processed} loaded, {skipped} skipped, {errors} errors")
```

**Step 3: Update `get_engine` in `db.py` to accept `pool_size`**

Current `get_engine` (line 12–13 in db.py):
```python
def get_engine(db_url: str) -> Engine:
    return create_engine(db_url)
```

Replace with:
```python
def get_engine(db_url: str, pool_size: int = 5) -> Engine:
    return create_engine(db_url, pool_size=pool_size, max_overflow=2)
```

Note: SQLite (used in tests) ignores `pool_size` — safe to pass for both.

**Step 4: Update imports in `main.py`**

Add `build_table_schemas` and `normalize_col_name` are already imported via:
```python
from loader.loader import load_file, normalize_col_name
```

Change that line to:
```python
from loader.loader import load_file, normalize_col_name, build_table_schemas
```

Also add to the top-level imports:
```python
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
```

**Step 5: Run full test suite**

```bash
.venv/bin/python -m pytest src/tests/ -v
```
Expected: all PASS

**Step 6: Commit**

```bash
git add main.py src/loader/db.py
git commit -m "feat: parallel init load — 3-phase pipeline with ThreadPoolExecutor"
```

---

### Task 5: Smoke test with sample_input

**Step 1: Start the database**

```bash
docker compose up -d
```

**Step 2: Run init with sample data**

```bash
time .venv/bin/python main.py --mode init
```

Watch the log output. You should see:
- `INIT — Phase 1: building table schemas from file headers`
- `SCHEMA — cancellation_bills — N columns`
- `INIT — Phase 2: loading N files (3 workers)`
- Files completing out of order (evidence of parallelism)
- `INIT — Phase 3: upgrading column types`

**Step 3: Verify row counts**

```bash
psql -h localhost -p 5433 -U postgres -d cms_db -c "
SELECT table_name, COUNT(*) as rows FROM (
  SELECT 'cancellation_bills' as table_name FROM cancellation_bills
  UNION ALL SELECT 'customer_data' FROM customer_data
  UNION ALL SELECT 'sales_revenue' FROM sales_revenue
) t GROUP BY table_name;
"
```

Row counts should match a sequential `init` run.

**Step 4: Run daily mode to confirm it is unaffected**

```bash
touch /tmp/dummy  # ensure mtime check is fresh if needed
.venv/bin/python main.py --mode daily
```

Expected: `0 files to process` (all files already loaded) or correct incremental behavior.

**Step 5: Final commit if any fixes needed**

```bash
git add -p
git commit -m "fix: <describe any fix>"
```

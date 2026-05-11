# Design: Parallel Init Load (Bulk Insert + ThreadPoolExecutor)

## Problem

`init` mode loads ~150 Excel files sequentially, row-by-row. Each row opens a separate DB
connection and commits individually. For files with 31k–86k rows, this is catastrophically
slow (estimated minutes per file). Total init time can exceed 30–60 minutes.

## Solution Overview

Three-phase pipeline for `init` mode only. `daily` mode is unchanged.

```
Phase 1: Schema Build  →  Phase 2: Parallel Bulk Load  →  Phase 3: Type Upgrade
(sequential, fast)         (ThreadPoolExecutor, N=3)        (sequential, unchanged)
```

## Phase 1: Schema Build (sequential)

**Goal:** build complete table schemas upfront so Phase 2 workers never need DDL.

Steps:
1. `scan_all_files()` — collect all file paths (unchanged)
2. `drop_table()` for each table (unchanged)
3. For each file: `pd.read_excel(path, nrows=0)` — read headers only (~1ms per file)
4. Build column union per table across all files
5. `CREATE TABLE` with all columns as `TEXT NULL` at once

New helper: `build_table_schemas(engine, files, cfg, logger)` in `loader.py`.
New helper: `create_table_with_columns(engine, table_name, columns)` in `db.py`.

Files that fail to open during header scan are marked `SKIP_FILE` and excluded from Phase 2.

## Phase 2: Parallel Bulk Load

**Goal:** load all files concurrently with bulk INSERT.

- `ThreadPoolExecutor(max_workers=3)`
- Each worker: read full Excel → bulk INSERT → log result
- No DDL in this phase → fully thread-safe
- Thread-safe progress counter via `threading.Lock`

**Bulk insert strategy** (replacing row-by-row loop in `load_file`):
- Split DataFrame into chunks of 500 rows
- For each chunk: attempt `executemany` (one transaction per chunk)
- If chunk fails: fall back to row-by-row for that chunk to preserve `SKIP_ROW` logging
- Result: ~100–500x faster for large files; SKIP_ROW behavior preserved on failure

**Connection pool:** `create_engine(db_url, pool_size=5, max_overflow=2)` to support 3 concurrent workers.

**Schema is already complete** from Phase 1 — `_ensure_table_schema` is skipped during parallel load.

## Phase 3: Type Upgrade (sequential)

Unchanged. After all workers finish:
```python
for table_name in loaded_tables:
    upgrade_column_types(engine, table_name, logger)
```
`ALTER COLUMN TYPE` requires an exclusive table lock — cannot be parallelized safely.

## Files Changed

| File | Change |
|------|--------|
| `src/loader/db.py` | Add `create_table_with_columns()` |
| `src/loader/loader.py` | Add `build_table_schemas()`; rewrite `load_file()` to use bulk insert with chunk fallback |
| `main.py` | Refactor `run()` init branch into 3 phases; add `ThreadPoolExecutor` |

**Unchanged:** `daily` mode, `run_script`, `upgrade_column_types`, all existing tests.

## Expected Speedup

| Bottleneck | Before | After |
|-----------|--------|-------|
| 86k-row file | ~4–8 min | ~5–15 sec |
| 150 files (sequential) | baseline | ~3x via parallelism |
| Total init | ~30–60 min (estimated) | ~2–5 min (estimated) |

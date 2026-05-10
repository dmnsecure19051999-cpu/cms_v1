# Design: TEXT-first Load + Post-init Type Upgrade

**Date:** 2026-05-10  
**Status:** Approved

## Problem

During `init` mode, the pipeline pre-scans all Excel files to infer column SQL types (FLOAT, TIMESTAMP, TEXT) using pandas dtype. This is unreliable because:

- A column may appear as `float64` dtype (most values are numeric) but contain actual text values like `"N/A"`, `"—"`, or mixed formats in some rows/files.
- Date columns have inconsistent formats across 70+ weekly files spanning 2020–2026.
- Result: many `SKIP_ROW` errors during the first full load.

This only affects `init` (one-time), not `daily` mode.

## Solution

**Load everything as TEXT first, then upgrade types from actual data in-database.**

### Init flow (changed)

```
init mode
  ├── Drop existing tables
  ├── Load all files — all columns created as TEXT, no type inference
  └── upgrade_column_types(engine, table_name) for each table
        └── For each column (except source_file):
              try ALTER COLUMN TYPE FLOAT USING col::FLOAT
              try ALTER COLUMN TYPE TIMESTAMP USING col::TIMESTAMP
              else keep TEXT
```

### Daily flow (unchanged)

Schema is already correct from init. New files insert into existing columns. New columns added as TEXT via existing `_ensure_table_schema` logic.

## Changes

| File | Change |
|------|--------|
| `loader/db.py` | Add `upgrade_column_types(engine, table_name, logger)` |
| `loader/loader.py` | `_ensure_table_schema` creates all columns as TEXT; remove `infer_group_schema` and `pre_create_table_schema` |
| `loader/excel_reader.py` | Remove `infer_sql_type` (no longer needed) |
| `loader/main.py` | Init: remove pre-schema step, call `upgrade_column_types` per table after all files loaded |
| `tests/test_db.py` | Add tests for `upgrade_column_types` |
| `tests/test_loader.py` | Update to reflect TEXT-only schema creation |
| `tests/test_excel_reader.py` | Remove `infer_sql_type` tests |

## `upgrade_column_types` logic

```python
def upgrade_column_types(engine, table_name, logger=None):
    skip_cols = {"source_file"}
    for col in get_table_columns(engine, table_name):
        if col in skip_cols:
            continue
        for sql_type, cast_expr in [("FLOAT", f'"{col}"::FLOAT'),
                                     ("TIMESTAMP", f'"{col}"::TIMESTAMP')]:
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
                pass  # try next type or keep TEXT
```

Each column attempt is its own transaction so one failure doesn't block the others.

## Trade-offs

- **Pro**: Zero insert errors during init; type detection based on actual data (not pandas guesses); daily mode untouched.
- **Con**: `ALTER TABLE` after full load is a table rewrite in PostgreSQL — acceptable for one-time init on local/dev DB; may be slow on very large tables.

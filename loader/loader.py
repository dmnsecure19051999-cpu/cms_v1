import pandas as pd
from sqlalchemy import Engine, text, inspect, types as sa_types


def _safe_col(name: str) -> str:
    return name.replace('"', '').replace("'", "").strip()


def _merge_sql_types(current: str | None, new_type: str) -> str:
    """Merge inferred SQL types conservatively to avoid type conflicts.

    Rules:
    - First seen type wins initially.
    - Same types keep the same.
    - Any conflict falls back to TEXT.
    """
    if current is None:
        return new_type
    if current == new_type:
        return current
    return "TEXT"


def infer_group_schema(file_list: list[dict], header_row: int, logger=None) -> dict[str, str]:
    """Infer per-column SQL types by scanning all files in a table group.

    Returns a mapping: column_name -> SQL type.
    """
    from loader.excel_reader import read_excel, infer_sql_type

    schema: dict[str, str] = {}
    files_scanned = 0

    for f in file_list:
        df, err = read_excel(f["file_path"], header=header_row)
        if err or df is None:
            if logger:
                logger.warning(f"PRE_SCHEMA_SKIP_FILE — {f['rel_path']} — cannot read: {err}")
            continue

        files_scanned += 1
        for col in df.columns:
            col_name = _safe_col(col)
            inferred = infer_sql_type(df[col])
            schema[col_name] = _merge_sql_types(schema.get(col_name), inferred)

    if logger and files_scanned:
        logger.info(
            f"PRE_SCHEMA_SCAN — files={files_scanned} columns={len(schema)}"
        )

    return schema


def _ensure_table_schema(engine: Engine, df: pd.DataFrame, table_name: str, logger):
    from loader.db import get_table_columns, add_column

    existing = get_table_columns(engine, table_name)
    if not existing:
        cols_sql = ", ".join(
            f'"{_safe_col(c)}" TEXT NULL' for c in df.columns
        ) + ', "source_file" TEXT NULL'
        with engine.connect() as conn:
            conn.execute(text(f'CREATE TABLE "{table_name}" ({cols_sql})'))
            conn.commit()
        return

    for col in df.columns:
        if col not in existing:
            add_column(engine, table_name, col, "TEXT")
            if logger:
                logger.info(f"NEW_COLUMN — {table_name} — added column: '{col}'")

    if "source_file" not in existing:
        add_column(engine, table_name, "source_file", "NVARCHAR(MAX)")


def pre_create_table_schema(engine: Engine, file_list: list[dict], table_name: str,
                             header_row: int, logger) -> None:
    """Scan all files for a table, infer schema, then pre-create/patch table."""
    from loader.excel_reader import read_excel_header
    from loader.db import get_table_columns, add_column

    file_cols: list[tuple[str, list[str]]] = []
    for f in file_list:
        cols, err = read_excel_header(f["file_path"], header_row)
        if not err and cols:
            file_cols.append((f["file_path"], cols))

    if not file_cols:
        return

    _, richest_cols = max(file_cols, key=lambda x: len(x[1]))

    seen: set[str] = {_safe_col(c) for c in richest_cols}
    all_cols: list[str] = [_safe_col(c) for c in richest_cols]
    for _, cols in file_cols:
        for c in cols:
            safe_c = _safe_col(c)
            if safe_c not in seen:
                seen.add(safe_c)
                all_cols.append(safe_c)

    # Infer SQL types from all files in this table group.
    inferred_schema = infer_group_schema(file_list, header_row, logger)
    for c in all_cols:
        inferred_schema.setdefault(c, "TEXT")

    if logger and inferred_schema:
        ordered = ", ".join(f"{c}:{inferred_schema[c]}" for c in sorted(inferred_schema.keys()))
        logger.info(f"PRE_SCHEMA_TYPES — {table_name} — {ordered}")

    existing = get_table_columns(engine, table_name)
    if not existing:
        col_defs = []
        for c in all_cols:
            sql_type = inferred_schema.get(c, "TEXT")
            col_defs.append(f'"{_safe_col(c)}" {sql_type} NULL')
        col_defs.append('"source_file" TEXT NULL')
        with engine.connect() as conn:
            conn.execute(text(f'CREATE TABLE "{table_name}" ({", ".join(col_defs)})'))
            conn.commit()
        if logger:
            logger.info(f"PRE_SCHEMA — {table_name} — created with {len(all_cols)} columns ({len(file_cols)} files scanned)")
    else:
        added = [c for c in all_cols if c not in existing]
        for col in added:
            add_column(engine, table_name, col, inferred_schema.get(col, "TEXT"))
        if logger and added:
            logger.info(f"PRE_SCHEMA — {table_name} — added {len(added)} missing columns")


def load_file(engine: Engine, df: pd.DataFrame, table_name: str,
              rel_path: str, logger) -> dict:
    from loader.db import upsert_load_metadata, is_file_loaded

    _ensure_table_schema(engine, df, table_name, logger)

    if is_file_loaded(engine, rel_path):
        with engine.connect() as conn:
            conn.execute(text(
                f'DELETE FROM "{table_name}" WHERE source_file = :fp'
            ), {"fp": rel_path})
            conn.commit()

    loaded = 0
    skipped = 0
    df = df.copy()
    df["source_file"] = rel_path

    col_info = inspect(engine).get_columns(table_name)
    existing_cols = [c["name"] for c in col_info]
    col_sa_types = {c["name"]: c["type"] for c in col_info}
    df = df[[c for c in df.columns if c in existing_cols]]

    for idx, row in df.iterrows():
        try:
            row_dict = {}
            for k, v in row.items():
                is_null = False
                try:
                    is_null = bool(pd.isna(v))
                except (TypeError, ValueError):
                    pass

                if is_null:
                    row_dict[_safe_col(k)] = None
                else:
                    sa_type = col_sa_types.get(k)
                    if sa_type is not None and isinstance(sa_type, sa_types.Numeric):
                        row_dict[_safe_col(k)] = float(v)
                    elif sa_type is not None and isinstance(sa_type, sa_types.Integer):
                        row_dict[_safe_col(k)] = int(v)
                    else:
                        row_dict[_safe_col(k)] = v

            col_names = list(row_dict.keys())
            col_values = list(row_dict.values())
            cols = ", ".join(f'"{c}"' for c in col_names)
            params = ", ".join(f":p{i}" for i in range(len(col_names)))
            param_dict = {f"p{i}": v for i, v in enumerate(col_values)}
            with engine.connect() as conn:
                conn.execute(text(f'INSERT INTO "{table_name}" ({cols}) VALUES ({params})'), param_dict)
                conn.commit()
            loaded += 1
        except Exception as e:
            skipped += 1
            if logger:
                logger.warning(f"SKIP_ROW — {rel_path} — row {idx} — {e}")

    status = "success" if skipped == 0 else "partial"
    upsert_load_metadata(engine, rel_path, table_name, loaded, status)
    return {"loaded": loaded, "skipped": skipped}

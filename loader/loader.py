import pandas as pd
from sqlalchemy import Engine, text, inspect


def _ensure_table_schema(engine: Engine, df: pd.DataFrame, table_name: str, logger):
    from loader.db import get_table_columns, add_column
    from loader.excel_reader import infer_sql_type

    existing = get_table_columns(engine, table_name)
    if not existing:
        cols_sql = ", ".join(
            f'"{c}" {infer_sql_type(df[c])} NULL' for c in df.columns
        ) + ', "source_file" TEXT NULL'
        with engine.connect() as conn:
            conn.execute(text(f'CREATE TABLE "{table_name}" ({cols_sql})'))
            conn.commit()
        return

    for col in df.columns:
        if col not in existing:
            add_column(engine, table_name, col, "NVARCHAR(MAX)")
            if logger:
                logger.info(f"NEW_COLUMN — {table_name} — added column: '{col}'")

    if "source_file" not in existing:
        add_column(engine, table_name, "source_file", "NVARCHAR(MAX)")


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
    col_type_map = {c["name"]: type(c["type"]).__name__.upper() for c in col_info}
    df = df[[c for c in df.columns if c in existing_cols]]

    for idx, row in df.iterrows():
        try:
            row_dict = {}
            for k, v in row.items():
                if pd.isna(v):
                    row_dict[k] = None
                else:
                    col_type = col_type_map.get(k, "")
                    if "FLOAT" in col_type or "REAL" in col_type or "DOUBLE" in col_type or "NUMERIC" in col_type or "DECIMAL" in col_type:
                        row_dict[k] = float(v)
                    elif "INT" in col_type:
                        row_dict[k] = int(v)
                    else:
                        row_dict[k] = v
            cols = ", ".join(f'"{k}"' for k in row_dict)
            params = ", ".join(f":{k}" for k in row_dict)
            with engine.connect() as conn:
                conn.execute(text(f'INSERT INTO "{table_name}" ({cols}) VALUES ({params})'), row_dict)
                conn.commit()
            loaded += 1
        except Exception as e:
            skipped += 1
            if logger:
                logger.warning(f"SKIP_ROW — {rel_path} — row {idx} — {e}")

    status = "success" if skipped == 0 else "partial"
    upsert_load_metadata(engine, rel_path, table_name, loaded, status)
    return {"loaded": loaded, "skipped": skipped}

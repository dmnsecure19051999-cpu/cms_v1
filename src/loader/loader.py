import pandas as pd
from sqlalchemy import Engine, inspect, text, types as sa_types

from loader.db import (
    add_column,
    get_table_columns,
    is_file_loaded,
    upsert_load_metadata,
)


def _safe_col(name: str) -> str:
    return name.replace('"', '').replace("'", "").strip()


def _coerce_value(v, sa_type) -> object:
    """Return v coerced to the SQLAlchemy column type, or None for NaN/NA."""
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(sa_type, sa_types.Numeric):
        return float(v)
    if isinstance(sa_type, sa_types.Integer):
        return int(v)
    return v


def _ensure_table_schema(engine: Engine, df: pd.DataFrame, table_name: str, logger) -> None:
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
        add_column(engine, table_name, "source_file", "TEXT")


def load_file(engine: Engine, df: pd.DataFrame, table_name: str,
              rel_path: str, logger) -> dict:
    _ensure_table_schema(engine, df, table_name, logger)

    if is_file_loaded(engine, rel_path):
        with engine.connect() as conn:
            conn.execute(
                text(f'DELETE FROM "{table_name}" WHERE source_file = :fp'),
                {"fp": rel_path},
            )
            conn.commit()

    df = df.copy()
    df["source_file"] = rel_path

    col_info = inspect(engine).get_columns(table_name)
    col_sa_types = {c["name"]: c["type"] for c in col_info}
    existing_cols = list(col_sa_types)
    df = df[[c for c in df.columns if c in existing_cols]]

    loaded = 0
    skipped = 0
    for idx, row in df.iterrows():
        try:
            row_dict = {
                _safe_col(k): _coerce_value(v, col_sa_types.get(k))
                for k, v in row.items()
            }
            cols = ", ".join(f'"{c}"' for c in row_dict)
            params = ", ".join(f":p{i}" for i in range(len(row_dict)))
            param_dict = {f"p{i}": v for i, v in enumerate(row_dict.values())}
            with engine.connect() as conn:
                conn.execute(
                    text(f'INSERT INTO "{table_name}" ({cols}) VALUES ({params})'),
                    param_dict,
                )
                conn.commit()
            loaded += 1
        except Exception as e:
            skipped += 1
            if logger:
                logger.warning(f"SKIP_ROW — {rel_path} — row {idx} — {e}")

    status = "success" if skipped == 0 else "partial"
    upsert_load_metadata(engine, rel_path, table_name, loaded, status)
    return {"loaded": loaded, "skipped": skipped}

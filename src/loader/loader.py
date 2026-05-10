import re
import unicodedata

import pandas as pd
from sqlalchemy import Engine, inspect, text, types as sa_types

from loader.db import (
    add_column,
    get_table_columns,
    is_file_loaded,
    upsert_load_metadata,
)


def normalize_col_name(name: str) -> str:
    name = str(name).replace("Đ", "D").replace("đ", "d")
    name = unicodedata.normalize("NFD", name)
    name = "".join(c for c in name if unicodedata.category(c) != "Mn")
    name = name.lower()
    name = name.replace("%", "per")
    name = name.replace("(", "").replace(")", "")
    name = re.sub(r"[^a-z0-9]+", "_", name)
    name = name.strip("_")
    return name or "col"


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
        if engine.dialect.name == "postgresql":
            uuid_def = '"uuid" UUID PRIMARY KEY DEFAULT gen_random_uuid()'
        else:
            uuid_def = '"uuid" TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16))))'
        cols_sql = (
            uuid_def + ", "
            + ", ".join(f'"{normalize_col_name(c)}" TEXT NULL' for c in df.columns)
            + ', "source_file" TEXT NULL'
        )
        with engine.connect() as conn:
            conn.execute(text(f'CREATE TABLE "{table_name}" ({cols_sql})'))
            conn.commit()
        return

    for col in df.columns:
        norm = normalize_col_name(col)
        if norm not in existing:
            add_column(engine, table_name, norm, "TEXT")
            if logger:
                logger.info(f"NEW_COLUMN — {table_name} — added column: '{norm}'")

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
    df.columns = [normalize_col_name(c) for c in df.columns]
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

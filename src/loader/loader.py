import re
import unicodedata
from collections import defaultdict

import pandas as pd
from sqlalchemy import Engine, inspect, text, types as sa_types

from loader.db import (
    add_column,
    create_table_with_columns,
    get_table_columns,
    is_file_loaded,
    insert_load_metadata,
    _uuid_col_def,
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


def _is_identifier_col(col_name: str | None) -> bool:
    if not col_name:
        return False
    lname = col_name.lower()
    return (
        lname == "id"
        or lname.startswith("id_")
        or lname.endswith("_id")
        or lname == "pid"
        or lname.startswith("pid_")
        or lname.endswith("_pid")
        or lname.startswith("ma_")
        or lname.startswith("stt_")
    )


def _is_relative_info_col(col_name: str | None) -> bool:
    return bool(col_name and col_name.lower() == "thong_tin_nguoi_than")


def _coerce_value(v, sa_type, col_name: str | None = None) -> object:
    """Return v coerced to the SQLAlchemy column type, or None for NaN/NA."""
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if _is_relative_info_col(col_name):
        if isinstance(v, str):
            stripped = v.strip()
            if re.fullmatch(r"\d+\.0+", stripped):
                return stripped.split(".", 1)[0]
            return stripped
        if isinstance(v, bool):
            return v
        try:
            numeric = float(v)
        except (TypeError, ValueError):
            return v
        else:
            if numeric.is_integer():
                return str(int(numeric))
            return str(v)
    if _is_identifier_col(col_name):
        if isinstance(v, str):
            stripped = v.strip()
            if stripped in {"", ".0"}:
                return None
            if re.fullmatch(r"[+-]?\d+(?:\.0+)?", stripped):
                return int(float(stripped))
            return stripped
        if isinstance(v, bool):
            return v
        try:
            numeric = float(v)
        except (TypeError, ValueError):
            return v
        else:
            if numeric.is_integer():
                return int(numeric)
    if isinstance(v, str) and v.strip() == ".0":
        return ""
    if isinstance(sa_type, sa_types.Numeric):
        return float(v)
    if isinstance(sa_type, sa_types.Integer):
        return int(v)
    return v


def build_table_schemas(engine, files: list[dict], cfg, logger) -> tuple[list[dict], int]:
    """Phase 1: read column headers only, create all tables with union schema.

    Returns (files_to_load, n_skipped) — files_to_load excludes unreadable files.
    """
    cols_by_table: dict[str, set[str]] = defaultdict(set)
    files_to_load = []
    n_skipped = 0

    for f in files:
        path = f["file_path"]
        rel = f["rel_path"]
        table = f["table_name"]
        header = cfg.table_header_map.get(table, 0)
        try:
            header_df = pd.read_excel(path, header=header, nrows=0, engine="openpyxl")
            norm_cols = [normalize_col_name(c) for c in header_df.columns]
            cols_by_table[table].update(norm_cols)
            files_to_load.append(f)
        except Exception as e:
            if logger:
                logger.warning(f"SKIP_FILE — {rel} — cannot read headers: {e}")
            insert_load_metadata(engine, rel, table, 0, "failed", "INSERT")
            n_skipped += 1

    for table_name, cols in cols_by_table.items():
        create_table_with_columns(engine, table_name, sorted(cols))
        if logger:
            logger.info(f"SCHEMA — {table_name} — {len(cols)} columns")

    return files_to_load, n_skipped


def _ensure_table_schema(engine: Engine, df: pd.DataFrame, table_name: str, logger) -> None:
    existing = get_table_columns(engine, table_name)
    if not existing:
        cols_sql = (
            _uuid_col_def(engine) + ", "
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
    df = df.copy()
    df.columns = [normalize_col_name(c) for c in df.columns]
    df = df.loc[:, ~df.columns.duplicated()]  # keep first when two raw cols normalize to same name

    _ensure_table_schema(engine, df, table_name, logger)

    already_loaded = is_file_loaded(engine, rel_path)
    operation = "UPDATE" if already_loaded else "INSERT"
    if already_loaded:
        with engine.connect() as conn:
            conn.execute(
                text(f'DELETE FROM "{table_name}" WHERE source_file = :fp'),
                {"fp": rel_path},
            )
            conn.commit()

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
                    f"p{i}": _coerce_value(v, col_sa_types.get(k), k)
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
        except Exception as bulk_exc:
            if logger:
                logger.warning(
                    f"BULK_FAIL — {rel_path} — chunk starting row {chunk_start} — {bulk_exc}"
                )
            # Fallback: row-by-row so individual bad rows are skipped
            with engine.connect() as conn:
                for idx, record in good_records:
                    try:
                        conn.execute(stmt, record)
                        conn.commit()
                        loaded += 1
                    except Exception as e:
                        skipped += 1
                        if logger:
                            logger.warning(f"SKIP_ROW — {rel_path} — row {idx} — {e}")

    status = "success" if skipped == 0 else "partial"
    insert_load_metadata(engine, rel_path, table_name, loaded, status, operation)
    return {"loaded": loaded, "skipped": skipped}

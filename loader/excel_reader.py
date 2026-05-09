import pandas as pd
from typing import Optional


def read_excel(path: str) -> tuple[Optional[pd.DataFrame], Optional[str]]:
    try:
        df = pd.read_excel(path, engine="openpyxl")
        df.columns = [str(c).strip() for c in df.columns]
        return df, None
    except Exception as e:
        return None, str(e)


def validate_columns(df: pd.DataFrame, required: list[str]) -> list[str]:
    return [c for c in required if c not in df.columns]


def detect_new_columns(df: pd.DataFrame, existing: list[str]) -> list[str]:
    return [c for c in df.columns if c not in existing and c != "source_file"]


def infer_sql_type(series: pd.Series) -> str:
    if pd.api.types.is_datetime64_any_dtype(series):
        return "DATETIME"
    if pd.api.types.is_numeric_dtype(series):
        return "FLOAT"
    return "NVARCHAR(MAX)"

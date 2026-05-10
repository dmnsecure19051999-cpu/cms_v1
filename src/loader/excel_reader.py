import pandas as pd
from typing import Optional


def read_excel(path: str, header: int = 0) -> tuple[Optional[pd.DataFrame], Optional[str]]:
    try:
        df = pd.read_excel(path, header=header, engine="openpyxl")
        df.columns = [str(c).strip() for c in df.columns]
        return df, None
    except Exception as e:
        return None, str(e)


def read_excel_header(path: str, header: int = 0) -> tuple[Optional[list[str]], Optional[str]]:
    try:
        df = pd.read_excel(path, header=header, nrows=0, engine="openpyxl")
        return [str(c).strip() for c in df.columns], None
    except Exception as e:
        return None, str(e)


def validate_columns(df: pd.DataFrame, required: list[str]) -> list[str]:
    return [c for c in required if c not in df.columns]


def detect_new_columns(df: pd.DataFrame, existing: list[str]) -> list[str]:
    return [c for c in df.columns if c not in existing and c != "source_file"]


import pandas as pd
import pytest
from pathlib import Path

@pytest.fixture
def sample_xlsx(tmp_path):
    df = pd.DataFrame({
        "bill_id": [1, 2, 3],
        "amount": [100.0, 200.0, 300.0],
        "created_at": pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"]),
        "note": ["a", "b", "c"],
    })
    path = tmp_path / "test.xlsx"
    df.to_excel(path, index=False)
    return path

def test_read_excel_returns_dataframe(sample_xlsx):
    from loader.excel_reader import read_excel
    df, error = read_excel(str(sample_xlsx))
    assert error is None
    assert len(df) == 3
    assert "bill_id" in df.columns

def test_validate_columns_ok(sample_xlsx):
    from loader.excel_reader import read_excel, validate_columns
    df, _ = read_excel(str(sample_xlsx))
    required = ["bill_id", "amount"]
    missing = validate_columns(df, required)
    assert missing == []

def test_validate_columns_missing(sample_xlsx):
    from loader.excel_reader import read_excel, validate_columns
    df, _ = read_excel(str(sample_xlsx))
    missing = validate_columns(df, ["bill_id", "nonexistent_col"])
    assert "nonexistent_col" in missing

def test_detect_new_columns(sample_xlsx):
    from loader.excel_reader import read_excel, detect_new_columns
    df, _ = read_excel(str(sample_xlsx))
    existing = ["bill_id", "amount"]
    new_cols = detect_new_columns(df, existing)
    assert set(new_cols) == {"created_at", "note"}

def test_infer_sql_type():
    from loader.excel_reader import infer_sql_type
    assert infer_sql_type(pd.Series([1.0, 2.0])) == "FLOAT"
    assert infer_sql_type(pd.Series(pd.to_datetime(["2025-01-01"]))) == "TIMESTAMP"
    assert infer_sql_type(pd.Series(["a", "b"])) == "TEXT"

def test_read_corrupt_file(tmp_path):
    bad = tmp_path / "bad.xlsx"
    bad.write_text("not an excel file")
    from loader.excel_reader import read_excel
    df, error = read_excel(str(bad))
    assert df is None
    assert error is not None

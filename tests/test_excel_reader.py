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


@pytest.fixture
def sample_xlsx_with_title_row(tmp_path):
    """Excel with a title row before headers (header on row 2, data from row 3)."""
    path = tmp_path / "with_title.xlsx"
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Report Title"])          # row 1 — title
    ws.append(["bill_id", "amount"])     # row 2 — headers
    ws.append([1, 100.0])                # row 3 — data
    ws.append([2, 200.0])
    wb.save(path)
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

def test_read_excel_header_returns_columns(sample_xlsx):
    from loader.excel_reader import read_excel_header
    cols, error = read_excel_header(str(sample_xlsx))
    assert error is None
    assert cols == ["bill_id", "amount", "created_at", "note"]


def test_read_excel_header_with_offset(sample_xlsx_with_title_row):
    from loader.excel_reader import read_excel_header
    cols, error = read_excel_header(str(sample_xlsx_with_title_row), header=1)
    assert error is None
    assert cols == ["bill_id", "amount"]


def test_read_excel_header_corrupt(tmp_path):
    from loader.excel_reader import read_excel_header
    bad = tmp_path / "bad.xlsx"
    bad.write_text("not excel")
    cols, error = read_excel_header(str(bad))
    assert cols is None
    assert error is not None


def test_read_excel_with_header_row(sample_xlsx_with_title_row):
    from loader.excel_reader import read_excel
    df, error = read_excel(str(sample_xlsx_with_title_row), header=1)
    assert error is None
    assert list(df.columns) == ["bill_id", "amount"]
    assert len(df) == 2


def test_read_corrupt_file(tmp_path):
    bad = tmp_path / "bad.xlsx"
    bad.write_text("not an excel file")
    from loader.excel_reader import read_excel
    df, error = read_excel(str(bad))
    assert df is None
    assert error is not None

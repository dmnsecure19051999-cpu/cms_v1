import time
from datetime import datetime, timezone
from pathlib import Path

def make_xlsx(path: Path):
    import pandas as pd
    pd.DataFrame({"a": [1]}).to_excel(path, index=False)

def test_scan_all_files(tmp_path):
    from loader.file_scanner import scan_all_files
    (tmp_path / "cancel").mkdir()
    (tmp_path / "customer_data").mkdir()
    (tmp_path / "revenue" / "Năm 2025").mkdir(parents=True)
    make_xlsx(tmp_path / "cancel" / "file1.xlsx")
    make_xlsx(tmp_path / "customer_data" / "file2.xlsx")
    make_xlsx(tmp_path / "revenue" / "Năm 2025" / "file3.xlsx")
    folder_map = {"cancel": "cancellation_bills", "customer_data": "customer_data", "revenue": "sales_revenue"}
    results = scan_all_files(str(tmp_path), folder_map)
    assert len(results) == 3

def test_scan_changed_files(tmp_path):
    from loader.file_scanner import scan_changed_files
    (tmp_path / "cancel").mkdir()
    make_xlsx(tmp_path / "cancel" / "old.xlsx")
    cutoff = datetime.now(tz=timezone.utc)
    time.sleep(0.05)
    make_xlsx(tmp_path / "cancel" / "new.xlsx")
    folder_map = {"cancel": "cancellation_bills"}
    results = scan_changed_files(str(tmp_path), folder_map, cutoff)
    paths = [r["file_path"] for r in results]
    assert any("new.xlsx" in p for p in paths)
    assert not any("old.xlsx" in p for p in paths)

def test_scan_result_has_table_name(tmp_path):
    from loader.file_scanner import scan_all_files
    (tmp_path / "cancel").mkdir()
    make_xlsx(tmp_path / "cancel" / "file.xlsx")
    folder_map = {"cancel": "cancellation_bills"}
    results = scan_all_files(str(tmp_path), folder_map)
    assert results[0]["table_name"] == "cancellation_bills"

def test_scan_missing_data_dir():
    from loader.file_scanner import scan_all_files
    import pytest
    with pytest.raises(FileNotFoundError):
        scan_all_files("/nonexistent/path", {"cancel": "cancellation_bills"})

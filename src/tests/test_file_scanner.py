import time
from datetime import datetime, timezone
from pathlib import Path


def make_xlsx(path: Path):
    import pandas as pd
    pd.DataFrame({"a": [1]}).to_excel(path, index=False)


def test_scan_all_files(tmp_path):
    from loader.file_scanner import scan_all_files
    cancel = tmp_path / "cancel"
    customer = tmp_path / "customer_data"
    revenue = tmp_path / "revenue" / "Năm 2025"
    cancel.mkdir()
    customer.mkdir()
    revenue.mkdir(parents=True)
    make_xlsx(cancel / "file1.xlsx")
    make_xlsx(customer / "file2.xlsx")
    make_xlsx(revenue / "file3.xlsx")
    folder_map = {
        str(tmp_path / "cancel"): "cancellation_bills",
        str(tmp_path / "customer_data"): "customer_data",
        str(tmp_path / "revenue"): "sales_revenue",
    }
    results = scan_all_files(folder_map)
    assert len(results) == 3


def test_scan_changed_files(tmp_path):
    from loader.file_scanner import scan_changed_files
    cancel = tmp_path / "cancel"
    cancel.mkdir()
    make_xlsx(cancel / "old.xlsx")
    cutoff = datetime.now(tz=timezone.utc)
    time.sleep(0.05)
    make_xlsx(cancel / "new.xlsx")
    folder_map = {str(cancel): "cancellation_bills"}
    results = scan_changed_files(folder_map, cutoff)
    paths = [r["file_path"] for r in results]
    assert any("new.xlsx" in p for p in paths)
    assert not any("old.xlsx" in p for p in paths)


def test_scan_result_has_table_name(tmp_path):
    from loader.file_scanner import scan_all_files
    cancel = tmp_path / "cancel"
    cancel.mkdir()
    make_xlsx(cancel / "file.xlsx")
    folder_map = {str(cancel): "cancellation_bills"}
    results = scan_all_files(folder_map)
    assert results[0]["table_name"] == "cancellation_bills"


def test_scan_result_rel_path_uses_folder_name(tmp_path):
    from loader.file_scanner import scan_all_files
    cancel = tmp_path / "cancel"
    cancel.mkdir()
    make_xlsx(cancel / "report.xlsx")
    folder_map = {str(cancel): "cancellation_bills"}
    results = scan_all_files(folder_map)
    assert results[0]["rel_path"] == "cancel/report.xlsx"


def test_scan_missing_folder():
    from loader.file_scanner import scan_all_files
    import pytest
    with pytest.raises(FileNotFoundError):
        scan_all_files({"/nonexistent/cancel": "cancellation_bills"})

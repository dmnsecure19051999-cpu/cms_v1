# CMS Data Pipeline Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Pipeline Python đọc file Excel từ 3 folder (cancel, customer_data, revenue), load vào SQL Server với 2 chế độ: init (toàn bộ) và daily (incremental theo modified time).

**Architecture:** pandas đọc Excel, SQLAlchemy quản lý schema và data, metadata table trong DB theo dõi trạng thái từng file và lịch sử run. Schema tự động mở rộng khi file mới có cột thêm.

**Tech Stack:** Python 3.11+, pandas, openpyxl, SQLAlchemy, pyodbc, python-dotenv, pytest, SQL Server 2022 (Docker)

---

## Task 1: Project scaffold + Docker setup

**Files:**
- Create: `docker-compose.yml`
- Create: `.env.example`
- Create: `requirements.txt`
- Create: `loader/__init__.py`
- Create: `tests/__init__.py`
- Create: `logs/.gitkeep`

**Step 1: Tạo docker-compose.yml**

```yaml
services:
  sqlserver:
    image: mcr.microsoft.com/mssql/server:2022-latest
    ports:
      - "1433:1433"
    environment:
      SA_PASSWORD: ${DB_PASSWORD}
      ACCEPT_EULA: "Y"
      MSSQL_DB: ${DB_NAME}
    volumes:
      - sqlserver_data:/var/opt/mssql

volumes:
  sqlserver_data:
```

**Step 2: Tạo .env.example**

```
DATA_DIR=/home/longdh5/cms
DB_HOST=localhost
DB_PORT=1433
DB_NAME=cms_db
DB_USER=sa
DB_PASSWORD=YourStrong@Password123
```

Copy thành `.env` thật và điền password thực.

**Step 3: Tạo requirements.txt**

```
pandas==2.2.3
openpyxl==3.1.5
sqlalchemy==2.0.36
pyodbc==5.2.0
python-dotenv==1.0.1
pytest==8.3.3
pytest-mock==3.14.0
```

**Step 4: Tạo các file __init__.py và logs/.gitkeep**

```bash
touch loader/__init__.py tests/__init__.py logs/.gitkeep
```

**Step 5: Khởi động Docker và kiểm tra**

```bash
docker compose up -d
docker compose ps
```

Expected: container `cms-sqlserver-1` status `Up`.

**Step 6: Commit**

```bash
git init
git add docker-compose.yml .env.example requirements.txt loader/__init__.py tests/__init__.py logs/.gitkeep
git commit -m "feat: project scaffold and docker setup"
```

---

## Task 2: config.py — đọc .env và folder→table mapping

**Files:**
- Create: `loader/config.py`
- Create: `tests/test_config.py`

**Step 1: Viết failing test**

```python
# tests/test_config.py
import os
import pytest
from unittest.mock import patch

def test_config_loads_data_dir():
    with patch.dict(os.environ, {
        "DATA_DIR": "/tmp/cms",
        "DB_HOST": "localhost", "DB_PORT": "1433",
        "DB_NAME": "cms_db", "DB_USER": "sa", "DB_PASSWORD": "pass"
    }):
        from loader.config import Config
        cfg = Config()
        assert cfg.data_dir == "/tmp/cms"

def test_config_folder_table_mapping():
    with patch.dict(os.environ, {
        "DATA_DIR": "/tmp/cms",
        "DB_HOST": "localhost", "DB_PORT": "1433",
        "DB_NAME": "cms_db", "DB_USER": "sa", "DB_PASSWORD": "pass"
    }):
        from loader.config import Config
        cfg = Config()
        assert cfg.folder_map["cancel"] == "cancellation_bills"
        assert cfg.folder_map["customer_data"] == "customer_data"
        assert cfg.folder_map["revenue"] == "sales_revenue"

def test_config_db_url():
    with patch.dict(os.environ, {
        "DATA_DIR": "/tmp/cms",
        "DB_HOST": "localhost", "DB_PORT": "1433",
        "DB_NAME": "cms_db", "DB_USER": "sa", "DB_PASSWORD": "pass"
    }):
        from loader.config import Config
        cfg = Config()
        assert "localhost" in cfg.db_url
        assert "cms_db" in cfg.db_url
```

**Step 2: Chạy test để xác nhận fail**

```bash
pytest tests/test_config.py -v
```

Expected: FAIL với `ModuleNotFoundError`.

**Step 3: Implement config.py**

```python
# loader/config.py
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    def __init__(self):
        self.data_dir = os.environ["DATA_DIR"]
        self.db_host = os.environ["DB_HOST"]
        self.db_port = os.environ.get("DB_PORT", "1433")
        self.db_name = os.environ["DB_NAME"]
        self.db_user = os.environ["DB_USER"]
        self.db_password = os.environ["DB_PASSWORD"]
        self.folder_map = {
            "cancel": "cancellation_bills",
            "customer_data": "customer_data",
            "revenue": "sales_revenue",
        }

    @property
    def db_url(self):
        return (
            f"mssql+pyodbc://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
            f"?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes"
        )
```

**Step 4: Chạy test để xác nhận pass**

```bash
pytest tests/test_config.py -v
```

Expected: 3 PASSED.

**Step 5: Commit**

```bash
git add loader/config.py tests/test_config.py
git commit -m "feat: config module with env loading and folder mapping"
```

---

## Task 3: logger.py — structured logging

**Files:**
- Create: `loader/logger.py`
- Create: `tests/test_logger.py`

**Step 1: Viết failing test**

```python
# tests/test_logger.py
import os, logging
from pathlib import Path

def test_logger_creates_log_file(tmp_path):
    from loader.logger import setup_logger
    log = setup_logger(log_dir=str(tmp_path), run_id="test123")
    log.info("hello")
    files = list(tmp_path.glob("*.log"))
    assert len(files) == 1

def test_logger_formats_message(tmp_path):
    from loader.logger import setup_logger
    log = setup_logger(log_dir=str(tmp_path), run_id="test123")
    log.warning("SKIP_FILE — somefile.xlsx — missing columns: ['id']")
    content = list(tmp_path.glob("*.log"))[0].read_text()
    assert "SKIP_FILE" in content
    assert "somefile.xlsx" in content
```

**Step 2: Chạy test để xác nhận fail**

```bash
pytest tests/test_logger.py -v
```

**Step 3: Implement logger.py**

```python
# loader/logger.py
import logging
import sys
from datetime import datetime
from pathlib import Path

def setup_logger(log_dir: str = "logs", run_id: str = "") -> logging.Logger:
    Path(log_dir).mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = Path(log_dir) / f"{ts}_{run_id}.log"

    fmt = "[%(asctime)s] %(levelname)-5s %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    logger = logging.getLogger(f"cms.{run_id}")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    fh = logging.FileHandler(filename, encoding="utf-8")
    fh.setFormatter(logging.Formatter(fmt, datefmt))
    logger.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(logging.Formatter(fmt, datefmt))
    logger.addHandler(sh)

    return logger
```

**Step 4: Chạy test**

```bash
pytest tests/test_logger.py -v
```

Expected: 2 PASSED.

**Step 5: Commit**

```bash
git add loader/logger.py tests/test_logger.py
git commit -m "feat: structured logger with file and stdout output"
```

---

## Task 4: db.py — engine, metadata tables, schema helpers

**Files:**
- Create: `loader/db.py`
- Create: `tests/test_db.py`

**Step 1: Viết failing test**

```python
# tests/test_db.py
import pytest
from sqlalchemy import create_engine, text, inspect

@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    return eng

def test_create_metadata_tables(engine):
    from loader.db import create_metadata_tables
    create_metadata_tables(engine)
    insp = inspect(engine)
    assert "_load_metadata" in insp.get_table_names()
    assert "_run_log" in insp.get_table_names()

def test_get_table_columns_empty(engine):
    from loader.db import create_metadata_tables, get_table_columns
    create_metadata_tables(engine)
    assert get_table_columns(engine, "nonexistent") == []

def test_add_column(engine):
    from loader.db import create_metadata_tables, add_column, get_table_columns
    create_metadata_tables(engine)
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE test_tbl (id INTEGER PRIMARY KEY)"))
        conn.commit()
    add_column(engine, "test_tbl", "new_col", "TEXT")
    cols = get_table_columns(engine, "test_tbl")
    assert "new_col" in cols

def test_get_last_run_time_none(engine):
    from loader.db import create_metadata_tables, get_last_run_time
    create_metadata_tables(engine)
    assert get_last_run_time(engine) is None
```

**Step 2: Chạy test để xác nhận fail**

```bash
pytest tests/test_db.py -v
```

**Step 3: Implement db.py**

```python
# loader/db.py
from datetime import datetime
from sqlalchemy import create_engine, text, inspect, Engine

def get_engine(db_url: str) -> Engine:
    return create_engine(db_url)

def create_metadata_tables(engine: Engine):
    with engine.connect() as conn:
        conn.execute(text("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = '_load_metadata')
            CREATE TABLE _load_metadata (
                id INT IDENTITY PRIMARY KEY,
                file_path NVARCHAR(500) NOT NULL,
                table_name NVARCHAR(100) NOT NULL,
                last_loaded_at DATETIME,
                row_count INT,
                status NVARCHAR(20)
            )
        """))
        conn.execute(text("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = '_run_log')
            CREATE TABLE _run_log (
                run_id INT IDENTITY PRIMARY KEY,
                mode NVARCHAR(10),
                started_at DATETIME,
                finished_at DATETIME,
                files_processed INT DEFAULT 0,
                files_skipped INT DEFAULT 0,
                errors INT DEFAULT 0
            )
        """))
        conn.commit()

def get_table_columns(engine: Engine, table_name: str) -> list[str]:
    insp = inspect(engine)
    if not insp.has_table(table_name):
        return []
    return [col["name"] for col in insp.get_columns(table_name)]

def add_column(engine: Engine, table_name: str, col_name: str, col_type: str = "NVARCHAR(MAX)"):
    with engine.connect() as conn:
        conn.execute(text(f'ALTER TABLE [{table_name}] ADD [{col_name}] {col_type} NULL'))
        conn.commit()

def get_last_run_time(engine: Engine) -> datetime | None:
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT MAX(started_at) FROM _run_log"
        )).fetchone()
        return row[0] if row else None

def upsert_load_metadata(engine: Engine, file_path: str, table_name: str,
                          row_count: int, status: str):
    with engine.connect() as conn:
        existing = conn.execute(text(
            "SELECT id FROM _load_metadata WHERE file_path = :fp"
        ), {"fp": file_path}).fetchone()
        if existing:
            conn.execute(text("""
                UPDATE _load_metadata
                SET last_loaded_at = :now, row_count = :rc, status = :st
                WHERE file_path = :fp
            """), {"now": datetime.now(), "rc": row_count, "st": status, "fp": file_path})
        else:
            conn.execute(text("""
                INSERT INTO _load_metadata (file_path, table_name, last_loaded_at, row_count, status)
                VALUES (:fp, :tn, :now, :rc, :st)
            """), {"fp": file_path, "tn": table_name, "now": datetime.now(),
                   "rc": row_count, "st": status})
        conn.commit()

def is_file_loaded(engine: Engine, file_path: str) -> bool:
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT id FROM _load_metadata WHERE file_path = :fp AND status = 'success'"
        ), {"fp": file_path}).fetchone()
        return row is not None

def insert_run_log(engine: Engine, mode: str, started_at: datetime) -> int:
    with engine.connect() as conn:
        result = conn.execute(text("""
            INSERT INTO _run_log (mode, started_at)
            OUTPUT INSERTED.run_id
            VALUES (:mode, :started_at)
        """), {"mode": mode, "started_at": started_at})
        run_id = result.fetchone()[0]
        conn.commit()
        return run_id

def finish_run_log(engine: Engine, run_id: int, processed: int, skipped: int, errors: int):
    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE _run_log
            SET finished_at = :now, files_processed = :p, files_skipped = :s, errors = :e
            WHERE run_id = :rid
        """), {"now": datetime.now(), "p": processed, "s": skipped, "e": errors, "rid": run_id})
        conn.commit()
```

**Step 4: Chú ý về test** — test dùng SQLite in-memory cho đơn giản, nhưng `IF NOT EXISTS` là T-SQL syntax không chạy trên SQLite. Refactor `create_metadata_tables` để dùng SQLAlchemy Table metadata thay vì raw SQL cho phần test:

Thêm vào `db.py` một variant dùng SQLAlchemy Core cho cross-db compatibility trong test:

```python
# Thêm vào db.py
from sqlalchemy import MetaData, Table, Column, Integer, String, DateTime

def create_metadata_tables(engine: Engine):
    meta = MetaData()
    Table("_load_metadata", meta,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("file_path", String(500), nullable=False),
        Column("table_name", String(100)),
        Column("last_loaded_at", DateTime),
        Column("row_count", Integer),
        Column("status", String(20)),
    )
    Table("_run_log", meta,
        Column("run_id", Integer, primary_key=True, autoincrement=True),
        Column("mode", String(10)),
        Column("started_at", DateTime),
        Column("finished_at", DateTime),
        Column("files_processed", Integer, default=0),
        Column("files_skipped", Integer, default=0),
        Column("errors", Integer, default=0),
    )
    meta.create_all(engine, checkfirst=True)
```

**Step 5: Chạy test**

```bash
pytest tests/test_db.py -v
```

Expected: 4 PASSED.

**Step 6: Commit**

```bash
git add loader/db.py tests/test_db.py
git commit -m "feat: db module with engine, metadata tables, schema helpers"
```

---

## Task 5: excel_reader.py — đọc và validate Excel

**Files:**
- Create: `loader/excel_reader.py`
- Create: `tests/test_excel_reader.py`

**Step 1: Viết failing test**

```python
# tests/test_excel_reader.py
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
    assert infer_sql_type(pd.Series(pd.to_datetime(["2025-01-01"]))) == "DATETIME"
    assert infer_sql_type(pd.Series(["a", "b"])) == "NVARCHAR(MAX)"

def test_read_corrupt_file(tmp_path):
    bad = tmp_path / "bad.xlsx"
    bad.write_text("not an excel file")
    from loader.excel_reader import read_excel
    df, error = read_excel(str(bad))
    assert df is None
    assert error is not None
```

**Step 2: Chạy test để xác nhận fail**

```bash
pytest tests/test_excel_reader.py -v
```

**Step 3: Implement excel_reader.py**

```python
# loader/excel_reader.py
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
```

**Step 4: Chạy test**

```bash
pytest tests/test_excel_reader.py -v
```

Expected: 6 PASSED.

**Step 5: Commit**

```bash
git add loader/excel_reader.py tests/test_excel_reader.py
git commit -m "feat: excel reader with column validation and type inference"
```

---

## Task 6: file_scanner.py — quét files thay đổi

**Files:**
- Create: `loader/file_scanner.py`
- Create: `tests/test_file_scanner.py`

**Step 1: Viết failing test**

```python
# tests/test_file_scanner.py
import os
import time
from datetime import datetime
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
    cutoff = datetime.now()
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
```

**Step 2: Chạy test để xác nhận fail**

```bash
pytest tests/test_file_scanner.py -v
```

**Step 3: Implement file_scanner.py**

```python
# loader/file_scanner.py
from datetime import datetime
from pathlib import Path

def _scan(data_dir: str, folder_map: dict, since: datetime | None) -> list[dict]:
    results = []
    base = Path(data_dir)
    for folder, table_name in folder_map.items():
        folder_path = base / folder
        if not folder_path.exists():
            continue
        for xlsx in folder_path.rglob("*.xlsx"):
            mtime = datetime.fromtimestamp(xlsx.stat().st_mtime)
            if since is None or mtime > since:
                results.append({
                    "file_path": str(xlsx),
                    "rel_path": str(xlsx.relative_to(base)),
                    "table_name": table_name,
                    "modified_at": mtime,
                })
    return results

def scan_all_files(data_dir: str, folder_map: dict) -> list[dict]:
    return _scan(data_dir, folder_map, since=None)

def scan_changed_files(data_dir: str, folder_map: dict, since: datetime) -> list[dict]:
    return _scan(data_dir, folder_map, since=since)
```

**Step 4: Chạy test**

```bash
pytest tests/test_file_scanner.py -v
```

Expected: 3 PASSED.

**Step 5: Commit**

```bash
git add loader/file_scanner.py tests/test_file_scanner.py
git commit -m "feat: file scanner with full and incremental scan modes"
```

---

## Task 7: loader.py — load data vào DB

**Files:**
- Create: `loader/loader.py`
- Create: `tests/test_loader.py`

**Step 1: Viết failing test**

```python
# tests/test_loader.py
import pandas as pd
import pytest
from sqlalchemy import create_engine, text, inspect

@pytest.fixture
def engine():
    return create_engine("sqlite:///:memory:")

def test_load_new_file(engine):
    from loader.loader import load_file
    from loader.db import create_metadata_tables
    create_metadata_tables(engine)
    df = pd.DataFrame({"bill_id": [1, 2], "amount": [100.0, 200.0]})
    stats = load_file(engine, df, "cancellation_bills", "cancel/test.xlsx", logger=None)
    assert stats["loaded"] == 2
    assert stats["skipped"] == 0

def test_load_adds_source_file_column(engine):
    from loader.loader import load_file
    from loader.db import create_metadata_tables
    from sqlalchemy import inspect as sa_inspect
    create_metadata_tables(engine)
    df = pd.DataFrame({"bill_id": [1], "amount": [100.0]})
    load_file(engine, df, "cancellation_bills", "cancel/test.xlsx", logger=None)
    cols = [c["name"] for c in sa_inspect(engine).get_columns("cancellation_bills")]
    assert "source_file" in cols

def test_reload_deletes_old_rows(engine):
    from loader.loader import load_file
    from loader.db import create_metadata_tables
    create_metadata_tables(engine)
    df1 = pd.DataFrame({"bill_id": [1, 2], "amount": [100.0, 200.0]})
    load_file(engine, df1, "cancellation_bills", "cancel/test.xlsx", logger=None)
    df2 = pd.DataFrame({"bill_id": [3], "amount": [300.0]})
    load_file(engine, df2, "cancellation_bills", "cancel/test.xlsx", logger=None)
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM cancellation_bills")).scalar()
    assert count == 1

def test_skip_row_on_bad_data(engine):
    from loader.loader import load_file
    from loader.db import create_metadata_tables
    create_metadata_tables(engine)
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE cancellation_bills (bill_id INTEGER, amount FLOAT, source_file TEXT)"))
        conn.commit()
    df = pd.DataFrame({"bill_id": [1, 2], "amount": ["not_a_number", 200.0]})
    stats = load_file(engine, df, "cancellation_bills", "cancel/test.xlsx", logger=None)
    assert stats["skipped"] >= 1
```

**Step 2: Chạy test để xác nhận fail**

```bash
pytest tests/test_loader.py -v
```

**Step 3: Implement loader.py**

```python
# loader/loader.py
import logging
import pandas as pd
from sqlalchemy import Engine, text, inspect

def _ensure_table_schema(engine: Engine, df: pd.DataFrame, table_name: str, logger):
    from loader.db import get_table_columns, add_column
    from loader.excel_reader import infer_sql_type

    existing = get_table_columns(engine, table_name)
    if not existing:
        cols_sql = ", ".join(
            f"[{c}] {infer_sql_type(df[c])} NULL" for c in df.columns
        ) + ", [source_file] NVARCHAR(500) NULL"
        with engine.connect() as conn:
            conn.execute(text(f"CREATE TABLE [{table_name}] ({cols_sql})"))
            conn.commit()
        return

    for col in df.columns:
        if col not in existing:
            add_column(engine, table_name, col, "NVARCHAR(MAX)")
            if logger:
                logger.info(f"NEW_COLUMN — {table_name} — added column: '{col}'")

    if "source_file" not in existing:
        add_column(engine, table_name, "source_file", "NVARCHAR(500)")

def load_file(engine: Engine, df: pd.DataFrame, table_name: str,
              rel_path: str, logger) -> dict:
    from loader.db import upsert_load_metadata, is_file_loaded

    _ensure_table_schema(engine, df, table_name, logger)

    if is_file_loaded(engine, rel_path):
        with engine.connect() as conn:
            conn.execute(text(
                f"DELETE FROM [{table_name}] WHERE source_file = :fp"
            ), {"fp": rel_path})
            conn.commit()

    loaded = 0
    skipped = 0
    df = df.copy()
    df["source_file"] = rel_path

    existing_cols = [c["name"] for c in inspect(engine).get_columns(table_name)]
    df = df[[c for c in df.columns if c in existing_cols]]

    for idx, row in df.iterrows():
        try:
            row_dict = {k: (None if pd.isna(v) else v) for k, v in row.items()}
            cols = ", ".join(f"[{k}]" for k in row_dict)
            params = ", ".join(f":{k}" for k in row_dict)
            with engine.connect() as conn:
                conn.execute(text(f"INSERT INTO [{table_name}] ({cols}) VALUES ({params})"), row_dict)
                conn.commit()
            loaded += 1
        except Exception as e:
            skipped += 1
            if logger:
                logger.warning(f"SKIP_ROW — {rel_path} — row {idx} — {e}")

    status = "success" if skipped == 0 else "partial"
    upsert_load_metadata(engine, rel_path, table_name, loaded, status)
    return {"loaded": loaded, "skipped": skipped}
```

**Step 4: Chạy test**

```bash
pytest tests/test_loader.py -v
```

Expected: 4 PASSED.

**Step 5: Commit**

```bash
git add loader/loader.py tests/test_loader.py
git commit -m "feat: loader module with schema auto-create, reload, and row-level error handling"
```

---

## Task 8: main.py — entrypoint orchestration

**Files:**
- Create: `loader/main.py`

**Step 1: Implement main.py**

```python
# loader/main.py
import argparse
import sys
from datetime import datetime

from loader.config import Config
from loader.db import (get_engine, create_metadata_tables, get_last_run_time,
                        insert_run_log, finish_run_log, upsert_load_metadata)
from loader.logger import setup_logger
from loader.file_scanner import scan_all_files, scan_changed_files
from loader.excel_reader import read_excel, validate_columns, detect_new_columns
from loader.loader import load_file
from loader.db import get_table_columns

def run(mode: str):
    cfg = Config()
    run_id_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    logger = setup_logger(log_dir="logs", run_id=run_id_str)

    engine = get_engine(cfg.db_url)
    create_metadata_tables(engine)

    run_id = insert_run_log(engine, mode, datetime.now())
    logger.info(f"Run started — mode={mode} run_id={run_id}")

    if mode == "init":
        files = scan_all_files(cfg.data_dir, cfg.folder_map)
    else:
        last_run = get_last_run_time(engine)
        if last_run is None:
            logger.info("No previous run found, scanning all files")
            files = scan_all_files(cfg.data_dir, cfg.folder_map)
        else:
            files = scan_changed_files(cfg.data_dir, cfg.folder_map, last_run)

    logger.info(f"Scanning: {len(files)} files to process")

    processed = skipped = errors = 0

    for f in files:
        path = f["file_path"]
        rel = f["rel_path"]
        table = f["table_name"]

        df, read_err = read_excel(path)
        if read_err:
            logger.warning(f"SKIP_FILE — {rel} — cannot read: {read_err}")
            upsert_load_metadata(engine, rel, table, 0, "failed")
            skipped += 1
            continue

        required = get_table_columns(engine, table)
        if required:
            missing = validate_columns(df, [c for c in required if c != "source_file"])
            if missing:
                logger.warning(f"SKIP_FILE — {rel} — missing columns: {missing}")
                upsert_load_metadata(engine, rel, table, 0, "skipped")
                skipped += 1
                continue

        stats = load_file(engine, df, table, rel, logger)
        processed += 1
        logger.info(f"LOADED — {rel} — {stats['loaded']} rows ({stats['skipped']} skipped)")

    finish_run_log(engine, run_id, processed, skipped, errors)
    logger.info(f"Run finished — {processed} loaded, {skipped} skipped, {errors} errors")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["init", "daily"], required=True)
    args = parser.parse_args()
    run(args.mode)

if __name__ == "__main__":
    main()
```

**Step 2: Smoke test thủ công (sau khi Docker đã chạy)**

```bash
# Copy .env.example thành .env và điền password
cp .env.example .env

# Cài dependencies
pip install -r requirements.txt

# Init load
python -m loader.main --mode init

# Kiểm tra log
ls logs/
```

Expected: file log mới, output dạng `Run finished — N loaded, M skipped, 0 errors`.

**Step 3: Commit**

```bash
git add loader/main.py
git commit -m "feat: main entrypoint with init and daily orchestration"
```

---

## Task 9: Chạy toàn bộ test suite

**Step 1: Chạy tất cả tests**

```bash
pytest tests/ -v --tb=short
```

Expected: tất cả PASSED.

**Step 2: Nếu có fail** — đọc error message, fix theo từng module tương ứng.

**Step 3: Commit final**

```bash
git add .
git commit -m "test: all tests passing"
```

---

## Task 10: Kiểm tra end-to-end với Docker

**Step 1: Khởi động SQL Server**

```bash
docker compose up -d
# Đợi ~20 giây cho SQL Server sẵn sàng
docker compose logs sqlserver | tail -5
```

Expected: `SQL Server is now ready for client connections`.

**Step 2: Tạo database**

```bash
docker exec -it cms-sqlserver-1 /opt/mssql-tools18/bin/sqlcmd \
  -S localhost -U sa -P "YourStrong@Password123" -No \
  -Q "CREATE DATABASE cms_db"
```

**Step 3: Init load**

```bash
python -m loader.main --mode init
```

Kiểm tra log output và đếm rows.

**Step 4: Daily load (giả lập file thay đổi)**

```bash
# Touch một file để thay đổi modified time
touch "/home/longdh5/cms/cancel/CancellationBillReport_20200101_20250216.xlsx"
python -m loader.main --mode daily
```

Expected: chỉ load 1 file đó.

**Step 5: Commit**

```bash
git add .
git commit -m "docs: add end-to-end test instructions"
```

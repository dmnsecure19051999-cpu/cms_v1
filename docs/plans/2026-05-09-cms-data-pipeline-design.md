# CMS Data Pipeline Design
**Date:** 2026-05-09  
**Stack:** Python, pandas, SQLAlchemy, SQL Server (Docker)

---

## Overview

Pipeline đọc file Excel từ folder SharePoint sync về local, load vào SQL Server. Hỗ trợ hai chế độ:
- `init` — load toàn bộ files lần đầu
- `daily` — load incremental các file thay đổi kể từ lần chạy cuối

---

## Architecture

```
cms/
├── .env                  # DATA_DIR, DB connection string
├── docker-compose.yml    # SQL Server container
├── loader/
│   ├── main.py           # entrypoint: --mode init | daily
│   ├── config.py         # đọc .env
│   ├── db.py             # SQLAlchemy engine, session, schema helpers
│   ├── file_scanner.py   # quét files, so sánh modified time vs metadata
│   ├── excel_reader.py   # đọc Excel, validate columns
│   ├── loader.py         # load data vào DB (insert / delete+insert)
│   └── logger.py         # structured logging ra file + stdout
├── logs/
└── requirements.txt
```

---

## Data Sources → Tables

| Folder | Pattern | Table |
|--------|---------|-------|
| `cancel/` | `CancellationBillReport_*.xlsx` | `cancellation_bills` |
| `customer_data/` | `CustomerReport_*.xlsx` | `customer_data` |
| `revenue/Năm */` | `PBI_SalesReport_*.xlsx` | `sales_revenue` |

Scan `revenue/` đệ quy vì có sub-folder theo năm.

---

## Metadata Tables

### `_load_metadata`
| Column | Type | Description |
|--------|------|-------------|
| id | INT PK | |
| file_path | NVARCHAR(500) | đường dẫn tương đối từ DATA_DIR |
| table_name | NVARCHAR(100) | |
| last_loaded_at | DATETIME | timestamp load thành công lần cuối |
| row_count | INT | số row đã load |
| status | NVARCHAR(20) | `success` / `failed` / `skipped` |

### `_run_log`
| Column | Type | Description |
|--------|------|-------------|
| run_id | INT PK IDENTITY | |
| mode | NVARCHAR(10) | `init` / `daily` |
| started_at | DATETIME | |
| finished_at | DATETIME | |
| files_processed | INT | |
| files_skipped | INT | |
| errors | INT | |

---

## Schema Validation & Column Handling

Mỗi file qua 3 bước:

**1. Required columns check**  
Required columns = tập hợp columns hiện có trong bảng DB (lần đầu lấy từ file đầu tiên load thành công).  
Nếu file thiếu bất kỳ required column → SKIP_FILE, ghi log, tiếp tục file tiếp theo.

**2. New columns detection**  
Nếu file có cột chưa tồn tại trong DB → `ALTER TABLE ADD COLUMN ... NVARCHAR(MAX) NULL`.  
Các row cũ sẽ có NULL ở cột mới (SQL Server default).

**3. Type inference**  
pandas infer type, map sang SQL:
- numeric → `FLOAT`
- datetime → `DATETIME`
- còn lại → `NVARCHAR(MAX)`
- Cột mới khi ALTER TABLE: luôn dùng `NVARCHAR(MAX)` để an toàn

**Tracking per-row source:**  
Mỗi row trong data tables có thêm cột `source_file NVARCHAR(500)` lưu tên file gốc. Dùng để DELETE khi reload.

---

## Daily Incremental Logic

```
for each file in DATA_DIR (modified_time > last_run_time):
    if file in _load_metadata (status=success):
        DELETE FROM table WHERE source_file = filename
    validate + load file
    update _load_metadata
```

`last_run_time` = `MAX(started_at)` từ `_run_log` với `mode='daily'` hoặc `'init'`.

---

## Error Handling

| Level | Trigger | Action |
|-------|---------|--------|
| `SKIP_FILE` | Thiếu required column, file corrupt | Bỏ qua file, log, tiếp tục |
| `SKIP_ROW` | Row không convert được sang đúng type | Bỏ qua row, log row index, tiếp tục |
| `ERROR` | DB connection fail, ALTER TABLE fail | Dừng run, log |

---

## Logging

Mỗi run tạo file `logs/YYYY-MM-DD_HH-MM-SS.log`. Format:

```
[2026-05-09 08:00:01] INFO  Run started — mode=daily
[2026-05-09 08:00:02] INFO  Scanning: 3 files changed since last run
[2026-05-09 08:00:03] WARN  SKIP_FILE — cancel/CancellationBillReport_20250303.xlsx — missing columns: ['bill_id']
[2026-05-09 08:00:04] INFO  NEW_COLUMN — customer_data — added column: 'phone_number'
[2026-05-09 08:00:05] WARN  SKIP_ROW — revenue/PBI_SalesReport_20260101.xlsx — row 42 — cannot convert 'N/A' to FLOAT in column 'revenue'
[2026-05-09 08:00:06] INFO  LOADED — revenue/PBI_SalesReport_20260101.xlsx — 847 rows (1 skipped)
[2026-05-09 08:00:07] INFO  Run finished — 2 loaded, 1 skipped, 0 errors
```

---

## Docker & Local Setup

**docker-compose.yml** — SQL Server 2022, data persisted via volume.

**.env:**
```
DATA_DIR=/home/longdh5/cms
DB_HOST=localhost
DB_PORT=1433
DB_NAME=cms_db
DB_USER=sa
DB_PASSWORD=YourPassword123
```

**requirements.txt:**
```
pandas
openpyxl
sqlalchemy
pyodbc
python-dotenv
```

**Usage:**
```bash
# Lần đầu
docker compose up -d
python loader/main.py --mode init

# Hàng ngày (cron / Task Scheduler)
python loader/main.py --mode daily
```

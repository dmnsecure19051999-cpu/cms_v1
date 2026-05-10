# CMS Data Pipeline

Đọc file Excel từ 3 thư mục (SharePoint-synced) và load vào PostgreSQL. Hỗ trợ 2 chế độ:

- **init** — load toàn bộ file, bỏ qua file đã load thành công trước đó
- **daily** — chỉ load file có thời gian sửa đổi mới hơn lần chạy cuối

---

## Cài đặt Ubuntu trên Windows (WSL2)

Nếu máy Windows chưa có Ubuntu, xem hướng dẫn từng bước tại:
**[docs/setup-windows-wsl.md](docs/setup-windows-wsl.md)**

---

## Yêu cầu

| | Windows | Ubuntu/Linux |
|---|---|---|
| Python | 3.10+ | 3.10+ |
| PostgreSQL | Cài sẵn hoặc remote | Cài sẵn / Docker |
| Docker | Không bắt buộc | Không bắt buộc |

---

## Cài đặt nhanh

### Windows

Mở **PowerShell** tại thư mục project:

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1
```

### Ubuntu / Linux

```bash
bash setup.sh
```

Script sẽ tự động:
1. Kiểm tra Python 3.10+
2. Tạo `.venv` và cài requirements
3. Tạo `.env` từ `.env.example` nếu chưa có
4. (Linux) Hỏi có muốn start PostgreSQL qua Docker không
5. Test kết nối database

---

## Cấu hình `.env`

Sau khi chạy setup, mở `.env` và điền thông tin:

```env
# Đường dẫn tới 3 thư mục dữ liệu (SharePoint sync)
CANCEL_DIR=C:\Users\...\SharePoint\cancel          # Windows
CUSTOMER_DATA_DIR=/home/user/sharepoint/customer_data  # Linux
REVENUE_DIR=/home/user/sharepoint/revenue

# Kết nối PostgreSQL
DB_HOST=localhost
DB_PORT=5432
DB_NAME=cms_db
DB_USER=postgres
DB_PASSWORD=your_password
```

> **Lưu ý:** Database sẽ được tự động tạo khi chạy pipeline lần đầu nếu chưa tồn tại.


## Chạy pipeline

### Windows

```powershell
# Lần đầu — load toàn bộ
.venv\Scripts\python -m loader.main --mode init

# Hàng ngày — chỉ load file mới
.venv\Scripts\python -m loader.main --mode daily
```

### Ubuntu / Linux

```bash
# Lần đầu — load toàn bộ
.venv/bin/python -m loader.main --mode init

# Hàng ngày — chỉ load file mới
.venv/bin/python -m loader.main --mode daily
```

---

## PostgreSQL với Docker (chỉ để test local)

File `docker-compose.yml` có sẵn để chạy PostgreSQL local:

```bash
docker compose up -d
```

Port mặc định: **5433** (dùng 5433 thay vì 5432 để tránh conflict với PostgreSQL đang cài sẵn).

Để dừng:

```bash
docker compose down
```

---

## Cấu trúc thư mục

```
cms/
├── loader/
│   ├── config.py        # Đọc .env, tạo DB URL
│   ├── db.py            # Tạo bảng, upsert metadata, run log
│   ├── excel_reader.py  # Đọc .xlsx, validate cột, infer SQL type
│   ├── file_scanner.py  # Quét folder, lọc file theo mtime
│   ├── loader.py        # Load DataFrame vào DB, xử lý schema
│   ├── logger.py        # Setup logging ra file + stdout
│   └── main.py          # Entrypoint CLI (--mode init/daily)
├── tests/               # Unit tests (pytest, SQLite in-memory)
├── logs/                # Log files (tự tạo khi chạy)
├── .env                 # Config local (KHÔNG commit)
├── .env.example         # Template cấu hình
├── docker-compose.yml   # PostgreSQL local
├── requirements.txt
├── setup.ps1            # Setup script cho Windows
└── setup.sh             # Setup script cho Ubuntu/Linux
```

### Các bảng trong database

| Bảng | Mô tả |
|------|-------|
| `cancellation_bills` | Dữ liệu từ thư mục `CANCEL_DIR` |
| `customer_data` | Dữ liệu từ thư mục `CUSTOMER_DATA_DIR` |
| `sales_revenue` | Dữ liệu từ thư mục `REVENUE_DIR` |
| `_load_metadata` | Trạng thái từng file đã load |
| `_run_log` | Lịch sử mỗi lần chạy pipeline |

---

## Log files

Log được lưu tại `logs/` với tên dạng `2026-05-09_19-30-00_1.log`.

Các mức log:

| Log | Ý nghĩa |
|-----|---------|
| `LOADED` | File load thành công |
| `SKIP_FILE` | File bị bỏ qua vì thiếu cột bắt buộc |
| `SKIP_ROW` | Một row bị lỗi khi insert, các row khác vẫn load |
| `NEW_COLUMN` | Phát hiện cột mới trong file, đã tự ALTER TABLE |

---

## Schema tự động

Khi file Excel có cột mới chưa tồn tại trong bảng DB, pipeline sẽ tự động `ALTER TABLE ADD COLUMN TEXT NULL` — không cần can thiệp thủ công.

Ngược lại, nếu file **thiếu cột bắt buộc** (cột đã có trong bảng do file trước tạo ra), file đó bị `SKIP_FILE`.

---

## Chạy tests

```bash
# Ubuntu
.venv/bin/python -m pytest tests/ -v

# Windows
.venv\Scripts\python -m pytest tests/ -v
```

---

## Troubleshooting

**Lỗi kết nối database**
```
connection to server at "localhost" failed
```
→ Kiểm tra DB_HOST, DB_PORT trong `.env`. Đảm bảo PostgreSQL đang chạy.

**`SKIP_FILE` — missing columns**
→ File không có đủ cột so với schema hiện tại. Kiểm tra file Excel có đúng định dạng không.

**Lỗi `could not find driver`** (Windows)
→ Đảm bảo đã cài `psycopg2-binary` trong `.venv`:
```powershell
.venv\Scripts\pip install psycopg2-binary==2.9.10
```

**`daily` mode không load file nào**
→ Không có file nào mới hơn lần chạy cuối. Kiểm tra `_run_log` trong DB hoặc chạy `--mode init`.

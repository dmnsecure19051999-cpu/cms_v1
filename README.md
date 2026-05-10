# CMS Data Pipeline

Đọc file Excel từ 3 thư mục (SharePoint-synced) và load vào PostgreSQL. Hỗ trợ 3 chế độ:

- **init** — drop toàn bộ bảng, load lại từ đầu, tự động upgrade kiểu dữ liệu sau khi load xong
- **daily** — chỉ load file có thời gian sửa đổi mới hơn lần chạy cuối
- **test** — load tối đa 10 file/bảng để kiểm tra nhanh

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

---

## Chạy pipeline

### Windows

```powershell
# Lần đầu — load toàn bộ
.venv\Scripts\python main.py --mode init

# Hàng ngày — chỉ load file mới
.venv\Scripts\python main.py --mode daily

# Kiểm tra nhanh — tối đa 10 file/bảng
.venv\Scripts\python main.py --mode test
```

### Ubuntu / Linux

```bash
# Lần đầu — load toàn bộ
.venv/bin/python main.py --mode init

# Hàng ngày — chỉ load file mới
.venv/bin/python main.py --mode daily

# Kiểm tra nhanh — tối đa 10 file/bảng
.venv/bin/python main.py --mode test
```

---

## PostgreSQL với Docker (chỉ để test local)

File `docker-compose.yml` có sẵn để chạy PostgreSQL local:

```bash
docker compose up -d
```

Port mặc định: **5433** (dùng 5433 thay vì 5432 để tránh conflict với PostgreSQL đang cài sẵn).

Để dừng và xóa toàn bộ data:

```bash
docker compose down -v
```

---

## Cấu trúc thư mục

```
cms/
├── main.py              # Entrypoint CLI (--mode init/daily/test)
├── src/
│   ├── loader/
│   │   ├── config.py        # Đọc .env, tạo DB URL, cấu hình header row per bảng
│   │   ├── db.py            # Tạo bảng, upsert metadata, run log, upgrade column types
│   │   ├── excel_reader.py  # Đọc .xlsx, validate cột
│   │   ├── file_scanner.py  # Quét folder, lọc file theo mtime
│   │   ├── loader.py        # Load DataFrame vào DB, xử lý schema động
│   │   └── logger.py        # Setup logging ra file + stdout
│   └── tests/               # Unit tests (pytest, SQLite in-memory)
├── sample_input/
│   ├── cancel/              # File Excel CancellationBillReport
│   ├── customer_data/       # File Excel CustomerReport
│   └── revenue/             # File Excel doanh thu (theo năm)
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

Log được lưu tại `logs/` với tên dạng `2026-05-10_19-30-00_20260510_193000.log`.

| Log | Ý nghĩa |
|-----|---------|
| `LOADED` | File load thành công |
| `SKIP_FILE` | File không đọc được (lỗi format) |
| `SKIP_ROW` | Một row bị lỗi khi insert, các row khác vẫn load |
| `NEW_COLUMN` | Phát hiện cột mới trong file, đã tự `ALTER TABLE ADD COLUMN` |
| `MISSING_COLS` | File thiếu cột so với schema — vẫn load, cột thiếu = `NULL` |
| `TYPE_UPGRADE` | Sau init: cột được upgrade từ `TEXT` → `FLOAT` hoặc `TIMESTAMP` |
| `PROGRESS` | Tiến độ xử lý file (ví dụ: `50/210 (23%)`) |

---

## Schema động

### Cột mới trong file mới

Nếu file Excel có cột chưa tồn tại trong bảng DB, pipeline tự động `ALTER TABLE ADD COLUMN TEXT NULL`. Các row cũ sẽ có `NULL` ở cột đó.

### File thiếu cột

Nếu file Excel thiếu cột so với schema hiện tại, pipeline vẫn load bình thường — cột thiếu nhận giá trị `NULL`.

### Upgrade kiểu dữ liệu (chỉ sau `init`)

Sau khi toàn bộ data được load dưới dạng `TEXT`, pipeline thử upgrade từng cột:
- Nếu toàn bộ giá trị cast được sang `FLOAT` → cột trở thành `FLOAT`
- Nếu không, thử `TIMESTAMP`
- Nếu cả hai đều fail → giữ `TEXT`

Đây là cách duy nhất đảm bảo không có lỗi insert khi data lịch sử có format không đồng nhất.

---

## Chạy tests

```bash
# Ubuntu
.venv/bin/python -m pytest src/tests/ -v

# Windows
.venv\Scripts\python -m pytest src/tests/ -v
```

---

## Troubleshooting

**Lỗi kết nối database**
```
connection to server at "localhost" failed
```
→ Kiểm tra `DB_HOST`, `DB_PORT` trong `.env`. Đảm bảo PostgreSQL đang chạy.

**`daily` mode không load file nào**
→ Không có file nào mới hơn lần chạy cuối. Kiểm tra `_run_log` trong DB hoặc chạy `--mode init`.

**Lỗi `could not find driver`** (Windows)
→ Đảm bảo đã cài `psycopg2-binary` trong `.venv`:
```powershell
.venv\Scripts\pip install psycopg2-binary==2.9.10
```

# CMS Data Pipeline

Đọc file Excel từ 3 thư mục (SharePoint-synced) và load vào PostgreSQL. Hỗ trợ các chế độ:

- **init** — lưu DDL views → drop views → drop tables → load lại từ đầu → upgrade kiểu dữ liệu → restore views
- **daily** — chỉ load file có thời gian sửa đổi mới hơn lần chạy cuối; tự động detect và archive file bị xóa
- **run_script** — chạy file `.sql` trong thư mục `script/`, export kết quả ra Excel

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
4. Khởi động PostgreSQL qua Docker
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
DB_PORT=5433
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
```

### Ubuntu / Linux

```bash
# Lần đầu — load toàn bộ
.venv/bin/python main.py --mode init

# Hàng ngày — chỉ load file mới
.venv/bin/python main.py --mode daily
```

---

## Chạy SQL script và export Excel

Đặt file `.sql` vào thư mục `script/`, kết quả export ra `output/`.

```bash
# Chạy toàn bộ script trong script/
.venv/bin/python main.py --mode run_script

# Chạy 1 script cụ thể
.venv/bin/python main.py --mode run_script --script script/my_query.sql
```

Output: `output/<tên_script>_YYYYMMDD_HHMMSS.xlsx`

---

## PostgreSQL với Docker

File `docker-compose.yml` có sẵn để chạy PostgreSQL local:

```bash
docker compose up -d
```

Port mặc định: **5433** (tránh conflict với PostgreSQL cài sẵn trên port 5432).

Để dừng và xóa toàn bộ data:

```bash
docker compose down -v
```

---

## Cấu trúc thư mục

```
cms/
├── main.py              # Entrypoint CLI
├── src/
│   ├── loader/
│   │   ├── config.py        # Đọc .env, tạo DB URL, cấu hình header row per bảng
│   │   ├── db.py            # Tạo bảng, metadata, run log, upgrade types, archive deleted
│   │   ├── excel_reader.py  # Đọc .xlsx, validate cột
│   │   ├── file_scanner.py  # Quét folder, lọc file theo mtime
│   │   ├── loader.py        # Load DataFrame vào DB, xử lý schema động
│   │   ├── logger.py        # Setup logging ra file + stdout
│   │   └── view_manager.py  # Lưu/drop/restore DB views xung quanh init
│   └── tests/               # Unit tests (pytest, SQLite in-memory)
├── sample_input/
│   ├── cancel/              # File Excel CancellationBillReport
│   ├── customer_data/       # File Excel CustomerReport
│   └── revenue/             # File Excel doanh thu (theo năm)
├── view/                # DDL của DB views (tự tạo khi init, có thể commit)
├── script/              # File .sql để query và export
├── output/              # Kết quả export Excel (tự tạo khi chạy run_script)
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
| `{tên_bảng}_deleted` | Rows được archive khi file nguồn bị xóa (tự tạo khi cần) |
| `_load_metadata` | Lịch sử append-only mỗi lần load file (có cột `operation`) |
| `_run_log` | Lịch sử mỗi lần chạy pipeline |

Mỗi bảng dữ liệu có cột `uuid UUID PRIMARY KEY` được sinh tự động (`gen_random_uuid()`).

#### Cột `operation` trong `_load_metadata`

Pipeline ghi một row mới vào `_load_metadata` mỗi khi xử lý file, không overwrite:

| Giá trị | Ý nghĩa |
|---------|---------|
| `INSERT` | File được load lần đầu |
| `UPDATE` | File đã tồn tại trong DB, load lại với dữ liệu mới |
| `DELETED` | File đã bị xóa khỏi thư mục nguồn, rows đã archive sang `*_deleted` |

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
| `TYPE_UPGRADE` | Cột được upgrade từ `TEXT` → `NUMERIC` hoặc `TIMESTAMP` |
| `PROGRESS` | Tiến độ xử lý file (ví dụ: `50/210 (23%)`) |
| `DELETED` | File bị xóa khỏi thư mục nguồn, rows đã archive sang `*_deleted` |
| `DELETE_FAILED` | Lỗi khi archive file bị xóa |
| `VIEW_SAVED` | DDL views đã lưu ra `view/` trước khi init drop tables |
| `VIEW_DROPPED` | Views đã drop trước khi init drop tables |
| `VIEW_RESTORED` | View đã recreate thành công sau khi init load xong |
| `VIEW_RESTORE_FAILED` | View không recreate được (DDL lỗi) — file DDL vẫn giữ trong `view/` |

---

## Schema động

### Cột mới trong file mới

Nếu file Excel có cột chưa tồn tại trong bảng DB, pipeline tự động `ALTER TABLE ADD COLUMN TEXT NULL`. Sau đó upgrade kiểu dữ liệu cho cột mới đó (cả trong `init` lẫn `daily`).

### File thiếu cột

Nếu file Excel thiếu cột so với schema hiện tại, pipeline vẫn load bình thường — cột thiếu nhận giá trị `NULL`.

### Upgrade kiểu dữ liệu

Sau khi data được load dưới dạng `TEXT`, pipeline thử upgrade từng cột:
- Nếu toàn bộ giá trị cast được sang `NUMERIC` → cột trở thành `NUMERIC` (lưu số thập phân chính xác)
- Nếu không, thử `TIMESTAMP`
- Nếu cả hai đều fail → giữ `TEXT`

Chạy sau `init` cho toàn bộ bảng. Chạy sau `daily` cho các cột mới phát sinh.

---

## Chạy tests

```bash
# Ubuntu
.venv/bin/python -m pytest src/tests/ -v

# Windows
.venv\Scripts\python -m pytest src/tests/ -v
```

---

## Xử lý file bị xóa (`daily` mode)

Khi chạy `daily`, pipeline so sánh danh sách file đang active trong `_load_metadata` với file thực tế trên disk. Nếu file đã biến mất:

1. Rows thuộc file đó trong bảng chính được copy sang `{tên_bảng}_deleted` (thêm cột `deleted_at`)
2. Rows trong bảng chính bị xóa
3. Ghi `DELETED` vào `_load_metadata`

Bảng `*_deleted` được tự tạo nếu chưa có. Dữ liệu archive không bao giờ bị xóa tự động.

---

## Quản lý Views (`init` mode)

Khi chạy `init`, pipeline tự động bảo tồn các user-defined views trong DB:

1. **Trước khi drop tables**: Lưu DDL của tất cả views ra `view/*.sql`, rồi drop views
2. **Sau khi load xong**: Recreate lại views từ các file `*.sql`

Nếu view nào restore thất bại (ví dụ: query của view tham chiếu cột đã bị đổi tên), pipeline log `VIEW_RESTORE_FAILED`, giữ file DDL trong `view/` để xử lý thủ công, và tiếp tục.

Folder `view/` có thể commit vào git để lưu lịch sử DDL views của project.

---

## Troubleshooting

**Lỗi kết nối database**
```
connection to server at "localhost" failed
```
→ Kiểm tra `DB_HOST`, `DB_PORT` trong `.env`. Đảm bảo PostgreSQL đang chạy (`docker compose up -d`).

**`daily` mode không load file nào**
→ Không có file nào có `mtime` mới hơn lần chạy cuối. Kiểm tra `_run_log` trong DB.

**Lỗi `could not find driver`** (Windows)
→ Đảm bảo đã cài `psycopg2-binary` trong `.venv`:
```powershell
.venv\Scripts\pip install psycopg2-binary==2.9.10
```

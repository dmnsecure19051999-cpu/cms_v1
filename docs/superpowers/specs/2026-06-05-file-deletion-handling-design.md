# File Deletion Handling — Design Spec

**Date:** 2026-06-05
**Status:** Approved

---

## Problem

Hiện tại `daily` mode chỉ phát hiện file mới hoặc file được update (dựa vào `mtime`). Khi một file bị xóa khỏi folder SharePoint-synced, dữ liệu vẫn còn nguyên trong DB mà không có cơ chế xử lý.

Yêu cầu: phát hiện file bị xóa, archive dữ liệu sang bảng `_deleted`, xóa khỏi bảng gốc, và ghi log đầy đủ.

---

## Goals

1. Phát hiện file bị xóa trong mỗi lần chạy `daily` mode
2. Archive rows sang `{table_name}_deleted` trước khi xóa
3. Ghi log từng operation (INSERT / UPDATE / DELETED) vào `_load_metadata` theo dạng append
4. Hiển thị log DELETED trong logger output

## Non-goals

- `init` mode không thay đổi (drop table → không cần archive)
- Không phát hiện xóa trong `run_script` mode

---

## Schema Changes

### `_load_metadata` — thêm column `operation`

```sql
ALTER TABLE _load_metadata ADD COLUMN IF NOT EXISTS operation TEXT;
```

Đổi từ upsert → INSERT mỗi lần. Mỗi operation tạo 1 row mới. Data cũ (NULL operation) được giữ nguyên.

**Cấu trúc sau thay đổi:**

| column | type | mô tả |
|--------|------|-------|
| id | INTEGER PK | auto increment |
| file_path | VARCHAR(500) | đường dẫn relative |
| table_name | VARCHAR(100) | tên bảng đích |
| last_loaded_at | DATETIME | thời điểm operation |
| row_count | INTEGER | số rows affected |
| status | VARCHAR(20) | `success` / `partial` / `failed` |
| operation | TEXT | `INSERT` / `UPDATE` / `DELETED` |

**Ví dụ:**

| id | file_path | operation | status | row_count | last_loaded_at |
|----|-----------|-----------|--------|-----------|----------------|
| 1 | cancel/file1.xlsx | INSERT | success | 100 | 2026-01-01 |
| 2 | cancel/file1.xlsx | UPDATE | success | 102 | 2026-01-10 |
| 3 | cancel/file1.xlsx | DELETED | success | 102 | 2026-02-01 |

### `{table_name}_deleted` — tạo on demand

Khi lần đầu cần archive, tạo bảng bằng cách clone cấu trúc từ bảng gốc + thêm `deleted_at`:

```sql
CREATE TABLE IF NOT EXISTS "{table_name}_deleted" AS
    SELECT * FROM "{table_name}" WHERE 1=0;

ALTER TABLE "{table_name}_deleted"
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP;
```

Bảng này mirror toàn bộ columns của bảng gốc tại thời điểm archive. Nếu bảng gốc sau đó có thêm column mới, `_deleted` sẽ không tự update — được chấp nhận vì archive là snapshot tại thời điểm xóa.

---

## File Deletion Detection

### Cơ chế

So sánh "file đang active trong DB" vs "file thực tế trên disk":

1. Query `_load_metadata`: lấy `operation` mới nhất của từng `file_path` (theo `last_loaded_at DESC`)
2. Lọc ra những file có `operation IN ('INSERT', 'UPDATE')` → đây là "active files"
3. Map `file_path` (relative) về absolute path qua `folder_map` trong Config
4. Kiểm tra từng file có tồn tại trên disk không
5. File không còn trên disk = deleted

### Function mới: `get_active_files(engine) -> list[dict]`

Trả về list `{file_path: str, table_name: str}` của các file đang active trong DB.

```sql
SELECT DISTINCT ON (file_path) file_path, table_name
FROM _load_metadata
WHERE operation IS NOT NULL
ORDER BY file_path, last_loaded_at DESC
-- filter: chỉ giữ row nếu operation mới nhất là INSERT hoặc UPDATE
```

Vì PostgreSQL hỗ trợ `DISTINCT ON`, dùng subquery để filter:

```sql
SELECT file_path, table_name
FROM (
    SELECT file_path, table_name, operation,
           ROW_NUMBER() OVER (PARTITION BY file_path ORDER BY last_loaded_at DESC) AS rn
    FROM _load_metadata
    WHERE operation IS NOT NULL
) t
WHERE rn = 1 AND operation IN ('INSERT', 'UPDATE')
```

---

## Archive & Delete Flow

Function: `archive_and_delete_file(engine, file_path, table_name, logger)`

Thực hiện trong **một transaction**:

### Bước 1 — Ensure `_deleted` table tồn tại

```sql
CREATE TABLE IF NOT EXISTS "{table_name}_deleted" AS
    SELECT * FROM "{table_name}" WHERE 1=0;
ALTER TABLE "{table_name}_deleted"
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP;
```

### Bước 2 — Copy rows sang `_deleted`

```sql
INSERT INTO "{table_name}_deleted"
SELECT *, NOW() AS deleted_at
FROM "{table_name}"
WHERE source_file = :fp;
```

Ghi lại `row_count` = số rows được copy (dùng `cursor.rowcount` hoặc `SELECT COUNT` trước).

### Bước 3 — Xóa rows khỏi bảng gốc

```sql
DELETE FROM "{table_name}" WHERE source_file = :fp;
```

### Bước 4 — Append vào `_load_metadata`

```
operation  = DELETED
status     = success
row_count  = số rows đã archive
```

Nếu exception ở bất kỳ bước nào → rollback toàn bộ transaction, log ERROR, ghi `_load_metadata` với `status = failed`.

### Log output

```
DELETED — cancel/file1.xlsx — 102 rows archived to cancellation_bills_deleted
```

---

## Code Changes

### `src/loader/db.py`

| Thay đổi | Mô tả |
|----------|-------|
| `create_metadata_tables()` | Thêm `ALTER TABLE _load_metadata ADD COLUMN IF NOT EXISTS operation TEXT` sau `meta.create_all()` |
| `upsert_load_metadata()` → `insert_load_metadata()` | Bỏ logic SELECT/UPDATE, chỉ INSERT, thêm param `operation: str` |
| `is_file_loaded()` | Đổi query: lấy row mới nhất của `file_path`, return True nếu `operation IN ('INSERT', 'UPDATE')` |
| Thêm `get_active_files()` | Trả về list file đang active (xem query ở trên) |
| Thêm `archive_and_delete_file()` | Toàn bộ flow archive (xem ở trên) |

### `src/loader/loader.py`

| Thay đổi | Mô tả |
|----------|-------|
| `load_file()` | Thêm param `operation: str`, truyền xuống `insert_load_metadata()` |

### `main.py`

| Thay đổi | Mô tả |
|----------|-------|
| `init` mode — gọi `load_file()` | Luôn truyền `operation="INSERT"` (vì drop table trước nên không có file nào đang loaded) |
| `daily` mode — gọi `load_file()` | Truyền `operation="UPDATE"` nếu `is_file_loaded()=True`, `"INSERT"` nếu lần đầu |
| `daily` mode — sau vòng loop chính | Thêm bước detect + xử lý deleted files: gọi `get_active_files()`, map về absolute path, check tồn tại, gọi `archive_and_delete_file()` cho từng file bị xóa |
| Counter `deleted` | Thêm biến đếm `deleted` song song với `processed`, `skipped`, `errors` |

### `src/tests/`

| File | Thay đổi |
|------|----------|
| `test_db.py` | Test `insert_load_metadata()`, `is_file_loaded()` với append logic, `get_active_files()`, `archive_and_delete_file()` |
| `test_loader.py` | Test `load_file()` với `operation` param |

---

## Không thay đổi

- `init` mode: vẫn drop table trực tiếp, không archive
- `run_script` mode: không liên quan
- `file_scanner.py`: không thay đổi
- `excel_reader.py`: không thay đổi
- `logger.py`: không thay đổi

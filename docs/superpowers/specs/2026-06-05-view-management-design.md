# View Management in Init Mode — Design Spec

**Date:** 2026-06-05
**Status:** Approved

---

## Problem

`init` mode hiện tại drop toàn bộ bảng mà không xử lý các view phụ thuộc. Nếu DB có user-defined views, chúng sẽ bị drop ngầm (cascade) hoặc gây lỗi khi drop table. Sau init, các views này biến mất vĩnh viễn.

Yêu cầu: trước khi drop tables, lưu DDL của toàn bộ user-defined views vào folder `view/`, sau khi load xong data thì recreate lại tất cả.

---

## Goals

1. Lưu DDL của tất cả user-defined views trong DB vào `view/` trước khi init xóa tables
2. Drop views trước khi drop tables (tránh dependency error)
3. Recreate views sau khi load xong data
4. Log đầy đủ VIEW_SAVED / VIEW_DROPPED / VIEW_RESTORED / VIEW_RESTORE_FAILED
5. View restore fail → giữ file DDL, log warning, tiếp tục

## Non-goals

- `daily` mode không thay đổi
- `run_script` mode không thay đổi
- Không quản lý view trên SQLite production (chỉ PostgreSQL production; SQLite dùng trong tests)

---

## Flow Thay Đổi — `init` mode

**Trước:**
```
1. Scan files
2. Drop tables
3. Phase 1: Build schemas
4. Phase 2: Load data
5. Phase 3: Upgrade column types
```

**Sau:**
```
1. Scan files
2. [NEW] Save views  → clear view/ → write DDL files
3. [NEW] Drop views  → trước khi drop tables
4. Drop tables
5. Phase 1: Build schemas
6. Phase 2: Load data
7. Phase 3: Upgrade column types
8. [NEW] Restore views từ view/*.sql
```

**Log output:**
```
VIEW_SAVED   — 3 views saved to view/
VIEW_DROPPED — 3 views dropped
...
VIEW_RESTORED       — revenue_summary
VIEW_RESTORE_FAILED — broken_view — column "x" does not exist
INIT — 2 views restored, 1 failed (DDL files kept in view/)
```

---

## Module Mới: `src/loader/view_manager.py`

### `save_views(engine: Engine, view_dir: Path) -> list[str]`

**Mục đích:** Lưu DDL của tất cả user-defined views vào `view_dir`.

**Logic:**
1. Query tất cả user-defined views từ DB (xem dialect section bên dưới)
2. Nếu không có view nào → return `[]`
3. Tạo `view_dir` nếu chưa tồn tại
4. Xóa toàn bộ `*.sql` cũ trong `view_dir`
5. Với mỗi view: ghi DDL ra `{view_name}.sql`. Nếu hai views ở hai schemas khác nhau có cùng tên → file thứ hai dùng `{schema}__{view_name}.sql` để tránh ghi đè.
6. Trả về list tên view đã lưu

**File format:**
```sql
CREATE OR REPLACE VIEW "public"."revenue_summary" AS
SELECT year, SUM(amount) AS total FROM sales_revenue GROUP BY year;
```

---

### `drop_all_views(engine: Engine) -> int`

**Mục đích:** Drop tất cả user-defined views trước khi drop tables.

**Logic:**
1. Query danh sách view hiện có
2. Nếu không có → return `0`
3. `DROP VIEW IF EXISTS "schema"."name" CASCADE` từng view
4. Trả về số view đã drop

**Lưu ý:** Dùng `CASCADE` để xử lý views phụ thuộc lẫn nhau. Nếu fail → raise exception (không thể drop tables an toàn).

---

### `restore_views(engine: Engine, view_dir: Path, logger) -> tuple[int, int]`

**Mục đích:** Recreate views từ `*.sql` files trong `view_dir`.

**Logic:**
1. Nếu `view_dir` không tồn tại hoặc không có `*.sql` file → return `(0, 0)`
2. Với mỗi `*.sql` file (sort theo tên để đảm bảo thứ tự nhất quán):
   - Execute SQL
   - Thành công → log `VIEW_RESTORED — {view_name}`, `restored += 1`
   - Thất bại → log `VIEW_RESTORE_FAILED — {view_name} — {error}`, **giữ file**, `failed += 1`
3. Trả về `(restored, failed)`

---

## Dialect Handling

| | PostgreSQL | SQLite (tests) |
|---|---|---|
| Query views | `SELECT schemaname, viewname, definition FROM pg_views WHERE schemaname NOT IN ('pg_catalog', 'information_schema')` | `SELECT name, sql FROM sqlite_master WHERE type='view'` |
| DDL saved | `CREATE OR REPLACE VIEW "{schema}"."{name}" AS\n{definition}` | SQL gốc từ `sqlite_master.sql` |
| Drop | `DROP VIEW IF EXISTS "{schema}"."{name}" CASCADE` | `DROP VIEW IF EXISTS "{name}"` |
| Restore | Execute file SQL as-is | Execute file SQL as-is |

**Lưu ý PostgreSQL:** `pg_views.definition` đôi khi đã có dấu `;` ở cuối. Normalize bằng cách strip trailing whitespace và semicolon trước khi lưu, rồi append `;` nhất quán.

---

## `view/` Folder

- Đặt tại project root: `view/`
- Tạo tự động nếu chưa có
- Thêm `view/.gitkeep` để git track folder rỗng (giống pattern `logs/`, `output/`)
- Không gitignore — DDL files có thể commit như một phần của project schema

---

## Error Handling

| Tình huống | Xử lý |
|-----------|-------|
| DB không có view nào | Skip save/drop/restore, không log gì thêm |
| `view_dir` chưa tồn tại | Tự tạo trong `save_views` |
| Lỗi ghi file khi save | Log warning `VIEW_SAVE_FAILED — name — error`, tiếp tục |
| `drop_all_views` fail | Raise exception — dừng init |
| View restore fail (DDL lỗi) | Log `VIEW_RESTORE_FAILED`, giữ file `.sql`, tiếp tục |
| `view_dir` rỗng khi restore | Return `(0, 0)`, không lỗi |

---

## Code Changes

### Files mới

| File | Mô tả |
|------|-------|
| `src/loader/view_manager.py` | Module mới: `save_views`, `drop_all_views`, `restore_views` |
| `src/tests/test_view_manager.py` | Tests cho module mới |
| `view/.gitkeep` | Track empty folder |

### Files thay đổi

| File | Thay đổi |
|------|----------|
| `main.py` | `init` mode: thêm steps 2, 3, 8. Import `save_views`, `drop_all_views`, `restore_views` từ `view_manager`. Log summary sau restore: `INIT — {restored} views restored, {failed} failed`. `view_dir = Path("view")` hardcoded. |

---

## Tests (`src/tests/test_view_manager.py`)

Tests dùng SQLite in-memory + `tmp_path` fixture pytest:

| Test | Mô tả |
|------|-------|
| `test_save_views_creates_sql_files` | Tạo đúng `*.sql` file per view |
| `test_save_views_clears_old_files` | Xóa file cũ trước khi lưu mới |
| `test_save_views_no_views_returns_empty` | DB không có view → `[]`, không tạo file |
| `test_drop_all_views_removes_views` | Views không còn tồn tại sau drop |
| `test_drop_all_views_no_views_returns_zero` | DB không có view → return `0` |
| `test_restore_views_recreates_views` | Views được recreate đúng từ file |
| `test_restore_views_failed_keeps_file` | DDL lỗi → file vẫn còn, return `(0, 1)` |
| `test_restore_views_empty_dir_returns_zero` | Folder rỗng → `(0, 0)` |
| `test_save_views_roundtrip` | Save → drop → restore → view hoạt động bình thường |

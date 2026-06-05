# View Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Trước khi `init` drop tables, lưu DDL của tất cả user-defined views vào `view/`, drop views, rồi recreate sau khi load xong.

**Architecture:** Tạo module `src/loader/view_manager.py` với 3 hàm (`save_views`, `drop_all_views`, `restore_views`). `main.py` gọi chúng ở đúng vị trí trong init flow. Dialect-aware: PostgreSQL prod dùng `pg_views`, SQLite tests dùng `sqlite_master`.

**Tech Stack:** Python 3.10+, SQLAlchemy 2.x, pathlib, pytest, PostgreSQL (prod) / SQLite in-memory (tests)

---

## File Map

| File | Thay đổi |
|------|----------|
| `src/loader/view_manager.py` | Tạo mới — `save_views`, `drop_all_views`, `restore_views` |
| `src/tests/test_view_manager.py` | Tạo mới — tests cho module trên |
| `main.py` | Thêm 3 bước vào init mode, import từ view_manager |
| `view/.gitkeep` | Tạo mới — track empty folder |

---

## Task 1: `save_views()` — lưu DDL views ra file

**Files:**
- Create: `src/loader/view_manager.py`
- Create: `src/tests/test_view_manager.py`

- [ ] **Step 1: Viết failing tests**

Tạo file `src/tests/test_view_manager.py`:

```python
import pytest
from pathlib import Path
from sqlalchemy import create_engine, text


@pytest.fixture
def engine():
    return create_engine("sqlite:///:memory:")


def _create_view(engine, name: str, sql: str):
    with engine.connect() as conn:
        conn.execute(text(f'CREATE VIEW "{name}" AS {sql}'))
        conn.commit()


def test_save_views_creates_sql_files(engine, tmp_path):
    from loader.view_manager import save_views
    _create_view(engine, "v_test", "SELECT 1 AS val")
    saved = save_views(engine, tmp_path)
    assert "v_test" in saved
    assert (tmp_path / "v_test.sql").exists()


def test_save_views_file_contains_ddl(engine, tmp_path):
    from loader.view_manager import save_views
    _create_view(engine, "v_revenue", "SELECT 42 AS amount")
    save_views(engine, tmp_path)
    content = (tmp_path / "v_revenue.sql").read_text()
    assert "v_revenue" in content
    assert "42" in content


def test_save_views_clears_old_files(engine, tmp_path):
    from loader.view_manager import save_views
    old_file = tmp_path / "old_view.sql"
    old_file.write_text("-- old")
    _create_view(engine, "v_new", "SELECT 1 AS x")
    save_views(engine, tmp_path)
    assert not old_file.exists()
    assert (tmp_path / "v_new.sql").exists()


def test_save_views_no_views_returns_empty(engine, tmp_path):
    from loader.view_manager import save_views
    result = save_views(engine, tmp_path)
    assert result == []


def test_save_views_creates_dir_if_missing(engine, tmp_path):
    from loader.view_manager import save_views
    new_dir = tmp_path / "subdir" / "views"
    _create_view(engine, "v_x", "SELECT 1 AS n")
    save_views(engine, new_dir)
    assert new_dir.exists()
    assert (new_dir / "v_x.sql").exists()
```

- [ ] **Step 2: Chạy tests để xác nhận fail**

```bash
.venv/bin/python -m pytest src/tests/test_view_manager.py -v
```

Expected: `ERROR — ImportError: cannot import name 'save_views'`

- [ ] **Step 3: Tạo `src/loader/view_manager.py` với `save_views`**

```python
from pathlib import Path
from sqlalchemy import Engine, text


def _get_user_views(engine: Engine) -> list[dict]:
    """Returns list of {name, schema, ddl} for all user-defined views."""
    with engine.connect() as conn:
        if engine.dialect.name == "postgresql":
            rows = conn.execute(text("""
                SELECT schemaname, viewname, definition
                FROM pg_views
                WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
                ORDER BY viewname
            """)).fetchall()
            return [
                {
                    "name": r[1],
                    "schema": r[0],
                    "ddl": (
                        f'CREATE OR REPLACE VIEW "{r[0]}"."{r[1]}" AS\n'
                        + r[2].rstrip().rstrip(";")
                        + ";"
                    ),
                }
                for r in rows
            ]
        else:
            rows = conn.execute(text(
                "SELECT name, sql FROM sqlite_master WHERE type='view' ORDER BY name"
            )).fetchall()
            return [
                {"name": r[0], "schema": None, "ddl": r[1].rstrip(";") + ";"}
                for r in rows
            ]


def save_views(engine: Engine, view_dir: Path) -> list[str]:
    views = _get_user_views(engine)
    if not views:
        return []

    view_dir.mkdir(parents=True, exist_ok=True)
    for old in view_dir.glob("*.sql"):
        old.unlink()

    saved_names: list[str] = []
    used_filenames: set[str] = set()

    for v in views:
        filename = f"{v['name']}.sql"
        if filename in used_filenames:
            prefix = v["schema"] or "default"
            filename = f"{prefix}__{v['name']}.sql"
        used_filenames.add(filename)
        (view_dir / filename).write_text(v["ddl"], encoding="utf-8")
        saved_names.append(v["name"])

    return saved_names


def drop_all_views(engine: Engine) -> int:
    raise NotImplementedError


def restore_views(engine: Engine, view_dir: Path, logger=None) -> tuple[int, int]:
    raise NotImplementedError
```

- [ ] **Step 4: Chạy tests**

```bash
.venv/bin/python -m pytest src/tests/test_view_manager.py::test_save_views_creates_sql_files src/tests/test_view_manager.py::test_save_views_file_contains_ddl src/tests/test_view_manager.py::test_save_views_clears_old_files src/tests/test_view_manager.py::test_save_views_no_views_returns_empty src/tests/test_view_manager.py::test_save_views_creates_dir_if_missing -v
```

Expected: 5 PASSED

- [ ] **Step 5: Chạy toàn bộ test suite để đảm bảo không regression**

```bash
.venv/bin/python -m pytest src/tests/ -v -q
```

Expected: tất cả PASSED

- [ ] **Step 6: Commit**

```bash
git add src/loader/view_manager.py src/tests/test_view_manager.py
git commit -m "feat: add save_views — saves user-defined view DDLs to view/ folder"
```

---

## Task 2: `drop_all_views()` — drop tất cả user-defined views

**Files:**
- Modify: `src/loader/view_manager.py`
- Modify: `src/tests/test_view_manager.py`

- [ ] **Step 1: Viết failing tests**

Thêm vào cuối `src/tests/test_view_manager.py`:

```python
def test_drop_all_views_removes_views(engine):
    from loader.view_manager import drop_all_views
    from sqlalchemy import inspect as sa_inspect
    _create_view(engine, "v_drop1", "SELECT 1 AS a")
    _create_view(engine, "v_drop2", "SELECT 2 AS b")
    count = drop_all_views(engine)
    assert count == 2
    view_names = [v for v in sa_inspect(engine).get_view_names()]
    assert "v_drop1" not in view_names
    assert "v_drop2" not in view_names


def test_drop_all_views_no_views_returns_zero(engine):
    from loader.view_manager import drop_all_views
    assert drop_all_views(engine) == 0
```

- [ ] **Step 2: Chạy tests để xác nhận fail**

```bash
.venv/bin/python -m pytest src/tests/test_view_manager.py::test_drop_all_views_removes_views src/tests/test_view_manager.py::test_drop_all_views_no_views_returns_zero -v
```

Expected: FAILED (`NotImplementedError`)

- [ ] **Step 3: Implement `drop_all_views` trong `src/loader/view_manager.py`**

Thay hàm `drop_all_views`:

```python
def drop_all_views(engine: Engine) -> int:
    views = _get_user_views(engine)
    if not views:
        return 0
    with engine.connect() as conn:
        for v in views:
            if engine.dialect.name == "postgresql":
                conn.execute(text(f'DROP VIEW IF EXISTS "{v["schema"]}"."{v["name"]}" CASCADE'))
            else:
                conn.execute(text(f'DROP VIEW IF EXISTS "{v["name"]}"'))
        conn.commit()
    return len(views)
```

- [ ] **Step 4: Chạy tests**

```bash
.venv/bin/python -m pytest src/tests/test_view_manager.py -v -q
```

Expected: tất cả PASSED

- [ ] **Step 5: Commit**

```bash
git add src/loader/view_manager.py src/tests/test_view_manager.py
git commit -m "feat: add drop_all_views — drops all user-defined views before table drop"
```

---

## Task 3: `restore_views()` — recreate views từ file

**Files:**
- Modify: `src/loader/view_manager.py`
- Modify: `src/tests/test_view_manager.py`

- [ ] **Step 1: Viết failing tests**

Thêm vào cuối `src/tests/test_view_manager.py`:

```python
def test_restore_views_recreates_views(engine, tmp_path):
    from loader.view_manager import save_views, drop_all_views, restore_views
    from sqlalchemy import inspect as sa_inspect
    _create_view(engine, "v_restore", "SELECT 99 AS n")
    save_views(engine, tmp_path)
    drop_all_views(engine)
    restored, failed = restore_views(engine, tmp_path, logger=None)
    assert restored == 1
    assert failed == 0
    assert "v_restore" in sa_inspect(engine).get_view_names()


def test_restore_views_failed_keeps_file(engine, tmp_path):
    from loader.view_manager import restore_views
    bad_sql_file = tmp_path / "broken_view.sql"
    bad_sql_file.write_text("CREATE VIEW broken_view AS SELECT * FROM nonexistent_table_xyz;")
    restored, failed = restore_views(engine, tmp_path, logger=None)
    assert restored == 0
    assert failed == 1
    assert bad_sql_file.exists()


def test_restore_views_empty_dir_returns_zero(engine, tmp_path):
    from loader.view_manager import restore_views
    restored, failed = restore_views(engine, tmp_path, logger=None)
    assert restored == 0
    assert failed == 0


def test_restore_views_missing_dir_returns_zero(engine, tmp_path):
    from loader.view_manager import restore_views
    missing = tmp_path / "no_such_dir"
    restored, failed = restore_views(engine, missing, logger=None)
    assert restored == 0
    assert failed == 0


def test_save_drop_restore_roundtrip(engine, tmp_path):
    from loader.view_manager import save_views, drop_all_views, restore_views
    from sqlalchemy import inspect as sa_inspect
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE t (id INTEGER, val TEXT)"))
        conn.commit()
    _create_view(engine, "v_roundtrip", "SELECT id, val FROM t")
    save_views(engine, tmp_path)
    drop_all_views(engine)
    assert "v_roundtrip" not in sa_inspect(engine).get_view_names()
    restore_views(engine, tmp_path, logger=None)
    assert "v_roundtrip" in sa_inspect(engine).get_view_names()
```

- [ ] **Step 2: Chạy tests để xác nhận fail**

```bash
.venv/bin/python -m pytest src/tests/test_view_manager.py::test_restore_views_recreates_views src/tests/test_view_manager.py::test_restore_views_failed_keeps_file src/tests/test_view_manager.py::test_restore_views_empty_dir_returns_zero src/tests/test_view_manager.py::test_restore_views_missing_dir_returns_zero src/tests/test_view_manager.py::test_save_drop_restore_roundtrip -v
```

Expected: FAILED (`NotImplementedError`)

- [ ] **Step 3: Implement `restore_views` trong `src/loader/view_manager.py`**

Thay hàm `restore_views`:

```python
def restore_views(engine: Engine, view_dir: Path, logger=None) -> tuple[int, int]:
    if not view_dir.exists():
        return 0, 0
    sql_files = sorted(view_dir.glob("*.sql"))
    if not sql_files:
        return 0, 0

    restored = 0
    failed = 0
    for sql_file in sql_files:
        view_name = sql_file.stem
        sql = sql_file.read_text(encoding="utf-8").strip()
        try:
            with engine.connect() as conn:
                conn.execute(text(sql))
                conn.commit()
            if logger:
                logger.info(f"VIEW_RESTORED — {view_name}")
            restored += 1
        except Exception as e:
            if logger:
                logger.warning(f"VIEW_RESTORE_FAILED — {view_name} — {e}")
            failed += 1
    return restored, failed
```

- [ ] **Step 4: Chạy toàn bộ test suite**

```bash
.venv/bin/python -m pytest src/tests/ -v -q
```

Expected: tất cả PASSED

- [ ] **Step 5: Commit**

```bash
git add src/loader/view_manager.py src/tests/test_view_manager.py
git commit -m "feat: add restore_views — recreates views from DDL files after init"
```

---

## Task 4: Tích hợp vào `main.py` và tạo `view/.gitkeep`

**Files:**
- Modify: `main.py`
- Create: `view/.gitkeep`

- [ ] **Step 1: Tạo `view/.gitkeep`**

```bash
mkdir -p view && touch view/.gitkeep
git add view/.gitkeep
```

- [ ] **Step 2: Cập nhật import trong `main.py`**

Tìm dòng:
```python
from loader.loader import load_file, normalize_col_name, build_table_schemas
```

Thêm ngay bên dưới:
```python
from loader.view_manager import save_views, drop_all_views, restore_views
```

- [ ] **Step 3: Thêm save + drop views vào init mode trong `main.py`**

Tìm đoạn:
```python
            table_names = {f["table_name"] for f in all_files}
            logger.info("INIT — dropping existing tables")
            for table_name in table_names:
                drop_table(engine, table_name)
```

Thay bằng:
```python
            table_names = {f["table_name"] for f in all_files}

            # Save and drop views before dropping tables
            view_dir = Path("view")
            saved_views = save_views(engine, view_dir)
            if saved_views:
                logger.info(f"VIEW_SAVED — {len(saved_views)} views saved to view/")
                n_dropped = drop_all_views(engine)
                logger.info(f"VIEW_DROPPED — {n_dropped} views dropped")

            logger.info("INIT — dropping existing tables")
            for table_name in table_names:
                drop_table(engine, table_name)
```

- [ ] **Step 4: Thêm restore views sau Phase 3 trong `main.py`**

Tìm đoạn (cuối init block):
```python
            # Phase 3: upgrade column types
            logger.info("INIT — Phase 3: upgrading column types")
            for table_name in loaded_tables:
                upgrade_column_types(engine, table_name, logger)
```

Thêm ngay sau vòng for đó:
```python
            # Phase 4: restore views
            if saved_views:
                logger.info("INIT — Phase 4: restoring views")
                restored, view_failed = restore_views(engine, view_dir, logger)
                logger.info(f"INIT — {restored} views restored, {view_failed} failed")
                if view_failed:
                    errors += view_failed
```

- [ ] **Step 5: Chạy toàn bộ test suite**

```bash
.venv/bin/python -m pytest src/tests/ -v -q
```

Expected: tất cả PASSED

- [ ] **Step 6: Commit**

```bash
git add main.py view/.gitkeep
git commit -m "feat: integrate view save/drop/restore into init mode"
```

---

## Kiểm tra thủ công (manual smoke test)

Sau khi tất cả tasks hoàn thành:

- [ ] **Tạo một view test trên DB thực, chạy init**

```sql
-- Tạo view thử (chạy trong psql hoặc pgAdmin)
CREATE VIEW test_revenue_summary AS
SELECT source_file, COUNT(*) AS row_count FROM sales_revenue GROUP BY source_file;
```

```bash
.venv/bin/python main.py --mode init
```

Kiểm tra:
1. File `view/test_revenue_summary.sql` tồn tại sau khi init
2. Log có dòng `VIEW_SAVED — 1 views saved to view/`
3. Log có dòng `VIEW_DROPPED — 1 views dropped`
4. Log có dòng `VIEW_RESTORED — test_revenue_summary`
5. View tồn tại lại trong DB sau khi init xong

- [ ] **Chạy lại init lần 2 (không có view trong DB, nhưng có file trong view/)**

```bash
.venv/bin/python main.py --mode init
```

Kiểm tra: File trong `view/` bị xóa (vì không có view nào trong DB để save), views được recreate từ... không — thực ra nếu DB không có view thì `saved_views = []` nên restore cũng bị skip. File `view/test_revenue_summary.sql` sẽ bị xóa ở bước `save_views` (vì không có view nào để save, nhưng `save_views` chỉ xóa old files nếu có views → thực ra `save_views` trả về `[]` khi không có view, VÀ không xóa files cũ trong trường hợp này).

**Lưu ý quan trọng cho implementer:** `save_views` chỉ xóa `*.sql` cũ khi có ít nhất 1 view trong DB (bước xóa file cũ nằm sau kiểm tra `if not views: return []`). Điều này đảm bảo: nếu DB không có view, folder `view/` được giữ nguyên (không xóa files cũ có thể do user đặt tay vào).

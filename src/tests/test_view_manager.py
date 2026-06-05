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

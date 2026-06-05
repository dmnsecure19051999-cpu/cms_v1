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


def restore_views(engine: Engine, view_dir: Path, logger=None) -> tuple[int, int]:
    raise NotImplementedError

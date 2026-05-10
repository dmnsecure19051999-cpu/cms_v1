from datetime import datetime, timezone
from pathlib import Path


def _scan(folder_map: dict, since: datetime | None) -> list[dict]:
    results = []
    for folder, table_name in folder_map.items():
        folder_path = Path(folder)
        if not folder_path.exists():
            raise FileNotFoundError(f"Folder does not exist: {folder}")
        for xlsx in folder_path.rglob("*.xlsx"):
            mtime = datetime.fromtimestamp(xlsx.stat().st_mtime, tz=timezone.utc)
            if since is None or mtime > since:
                rel_path = f"{folder_path.name}/{xlsx.relative_to(folder_path).as_posix()}"
                results.append({
                    "file_path": str(xlsx),
                    "rel_path": rel_path,
                    "table_name": table_name,
                    "modified_at": mtime,
                })
    return results


def scan_all_files(folder_map: dict) -> list[dict]:
    return _scan(folder_map, since=None)


def scan_changed_files(folder_map: dict, since: datetime) -> list[dict]:
    return _scan(folder_map, since=since)

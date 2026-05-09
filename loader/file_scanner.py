from datetime import datetime
from pathlib import Path


def _scan(data_dir: str, folder_map: dict, since: datetime | None) -> list[dict]:
    results = []
    base = Path(data_dir)
    for folder, table_name in folder_map.items():
        folder_path = base / folder
        if not folder_path.exists():
            continue
        for xlsx in folder_path.rglob("*.xlsx"):
            mtime = datetime.fromtimestamp(xlsx.stat().st_mtime)
            if since is None or mtime > since:
                results.append({
                    "file_path": str(xlsx),
                    "rel_path": str(xlsx.relative_to(base)),
                    "table_name": table_name,
                    "modified_at": mtime,
                })
    return results


def scan_all_files(data_dir: str, folder_map: dict) -> list[dict]:
    return _scan(data_dir, folder_map, since=None)


def scan_changed_files(data_dir: str, folder_map: dict, since: datetime) -> list[dict]:
    return _scan(data_dir, folder_map, since=since)

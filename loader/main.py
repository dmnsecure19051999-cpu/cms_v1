# loader/main.py
import argparse
from collections import defaultdict
from datetime import datetime, timezone

from loader.config import Config
from loader.db import (get_engine, ensure_database, create_metadata_tables,
                        get_last_run_time, insert_run_log, finish_run_log,
                        upsert_load_metadata, get_table_columns, drop_table,
                        upgrade_column_types)
from loader.logger import setup_logger
from loader.file_scanner import scan_all_files, scan_changed_files
from loader.excel_reader import read_excel, validate_columns
from loader.loader import load_file


def run(mode: str):
    cfg = Config()
    start_time = datetime.now(tz=timezone.utc)
    run_id_str = start_time.strftime("%Y%m%d_%H%M%S")
    logger = setup_logger(log_dir="logs", run_id=run_id_str)

    try:
        ensure_database(cfg.db_url)
        engine = get_engine(cfg.db_url)
        create_metadata_tables(engine)
    except Exception as e:
        logger.critical(f"DB bootstrap failed: {e}")
        raise

    run_id = insert_run_log(engine, mode, start_time)
    logger.info(f"Run started — mode={mode} run_id={run_id}")

    if mode in ("init", "test"):
        files = scan_all_files(cfg.folder_map)
    else:
        last_run = get_last_run_time(engine)
        if last_run is None:
            logger.info("No previous run found, scanning all files")
            files = scan_all_files(cfg.folder_map)
        else:
            if last_run.tzinfo is None:
                last_run = last_run.replace(tzinfo=timezone.utc)
            files = scan_changed_files(cfg.folder_map, last_run)

    if mode == "test":
        table_buckets: dict[str, list] = defaultdict(list)
        for f in files:
            table_buckets[f["table_name"]].append(f)
        files = [f for bucket in table_buckets.values() for f in bucket[:10]]
        logger.info(f"Test mode: limited to {len(files)} files (up to 10 per table)")
        logger.info("Test mode: column type upgrade skipped — run --mode init for full pipeline")

    if mode == "init":
        table_names = {f["table_name"] for f in files}
        logger.info("INIT — dropping existing tables")
        for table_name in table_names:
            drop_table(engine, table_name)

    logger.info(f"Scanning: {len(files)} files to process")

    processed = skipped = errors = 0
    loaded_tables: set[str] = set()

    try:
        for f in files:
            path = f["file_path"]
            rel = f["rel_path"]
            table = f["table_name"]

            header = cfg.table_header_map.get(table, 0)
            df, read_err = read_excel(path, header=header)
            if read_err:
                logger.warning(f"SKIP_FILE — {rel} — cannot read: {read_err}")
                upsert_load_metadata(engine, rel, table, 0, "failed")
                skipped += 1
                continue

            existing = get_table_columns(engine, table)
            missing = validate_columns(df, [c for c in existing if c != "source_file"])
            if missing:
                logger.info(f"MISSING_COLS — {rel} — {missing} will be NULL")

            try:
                stats = load_file(engine, df, table, rel, logger)
                processed += 1
                loaded_tables.add(table)
                logger.info(f"LOADED — {rel} — {stats['loaded']} rows ({stats['skipped']} skipped)")
            except Exception as e:
                errors += 1
                logger.error(f"ERROR — {rel} — {e}")
                upsert_load_metadata(engine, rel, table, 0, "failed")

        if mode == "init":
            logger.info("INIT — upgrading column types from actual data")
            for table_name in loaded_tables:
                upgrade_column_types(engine, table_name, logger)

    finally:
        finish_run_log(engine, run_id, processed, skipped, errors)
        logger.info(f"Run finished — {processed} loaded, {skipped} skipped, {errors} errors")


def main():
    parser = argparse.ArgumentParser(description="CMS data pipeline loader")
    parser.add_argument("--mode", choices=["init", "daily", "test"], required=True,
                        help="init: load all files; daily: load changed files since last run; test: load up to 10 files per table")
    args = parser.parse_args()
    run(args.mode)


if __name__ == "__main__":
    main()

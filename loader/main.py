# loader/main.py
import argparse
from datetime import datetime, timezone

from loader.config import Config
from loader.db import (get_engine, create_metadata_tables, get_last_run_time,
                        insert_run_log, finish_run_log, upsert_load_metadata,
                        get_table_columns)
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
        engine = get_engine(cfg.db_url)
        create_metadata_tables(engine)
    except Exception as e:
        logger.critical(f"DB bootstrap failed: {e}")
        raise

    run_id = insert_run_log(engine, mode, start_time)
    logger.info(f"Run started — mode={mode} run_id={run_id}")

    if mode == "init":
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

    logger.info(f"Scanning: {len(files)} files to process")

    processed = skipped = errors = 0

    try:
        for f in files:
            path = f["file_path"]
            rel = f["rel_path"]
            table = f["table_name"]

            df, read_err = read_excel(path)
            if read_err:
                logger.warning(f"SKIP_FILE — {rel} — cannot read: {read_err}")
                upsert_load_metadata(engine, rel, table, 0, "failed")
                skipped += 1
                continue

            required = [c for c in get_table_columns(engine, table) if c != "source_file"]
            if required:
                missing = validate_columns(df, required)
                if missing:
                    logger.warning(f"SKIP_FILE — {rel} — missing columns: {missing}")
                    upsert_load_metadata(engine, rel, table, 0, "skipped")
                    skipped += 1
                    continue

            try:
                stats = load_file(engine, df, table, rel, logger)
                processed += 1
                logger.info(f"LOADED — {rel} — {stats['loaded']} rows ({stats['skipped']} skipped)")
            except Exception as e:
                errors += 1
                logger.error(f"ERROR — {rel} — {e}")
                upsert_load_metadata(engine, rel, table, 0, "failed")
    finally:
        finish_run_log(engine, run_id, processed, skipped, errors)
        logger.info(f"Run finished — {processed} loaded, {skipped} skipped, {errors} errors")


def main():
    parser = argparse.ArgumentParser(description="CMS data pipeline loader")
    parser.add_argument("--mode", choices=["init", "daily"], required=True,
                        help="init: load all files; daily: load changed files since last run")
    args = parser.parse_args()
    run(args.mode)


if __name__ == "__main__":
    main()

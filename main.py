import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

import argparse
from collections import defaultdict
from datetime import datetime, timezone

import pandas as pd

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

    last_run = get_last_run_time(engine) if mode == "daily" else None

    run_id = insert_run_log(engine, mode, start_time)
    logger.info(f"Run started — mode={mode} run_id={run_id}")

    if mode == "init":
        files = scan_all_files(cfg.folder_map)
    else:
        if last_run is None:
            logger.info("No previous run found, scanning all files")
            files = scan_all_files(cfg.folder_map)
        else:
            if last_run.tzinfo is None:
                last_run = last_run.replace(tzinfo=timezone.utc)
            files = scan_changed_files(cfg.folder_map, last_run)

    if mode == "init":
        table_names = {f["table_name"] for f in files}
        logger.info("INIT — dropping existing tables")
        for table_name in table_names:
            drop_table(engine, table_name)

    logger.info(f"Scanning: {len(files)} files to process")

    processed = skipped = errors = 0
    loaded_tables: set[str] = set()
    new_cols_by_table: dict[str, set[str]] = defaultdict(set)
    total = len(files)

    try:
        for idx, f in enumerate(files, 1):
            path = f["file_path"]
            rel = f["rel_path"]
            table = f["table_name"]

            header = cfg.table_header_map.get(table, 0)
            df, read_err = read_excel(path, header=header)
            if read_err:
                logger.warning(f"SKIP_FILE — {rel} — cannot read: {read_err}")
                upsert_load_metadata(engine, rel, table, 0, "failed")
                skipped += 1
                logger.info(f"PROGRESS — {idx}/{total} ({idx*100//total}%)")
                continue

            existing = get_table_columns(engine, table)
            schema_cols = [c for c in existing if c not in ("source_file", "uuid")]
            missing = validate_columns(df, schema_cols)
            if missing:
                logger.info(f"MISSING_COLS — {rel} — {missing} will be NULL")

            new_cols = [c for c in df.columns if c not in existing]

            try:
                stats = load_file(engine, df, table, rel, logger)
                processed += 1
                loaded_tables.add(table)
                if new_cols:
                    new_cols_by_table[table].update(new_cols)
                logger.info(f"LOADED — {rel} — {stats['loaded']} rows ({stats['skipped']} skipped)")
            except Exception as e:
                errors += 1
                logger.error(f"ERROR — {rel} — {e}")
                upsert_load_metadata(engine, rel, table, 0, "failed")

            logger.info(f"PROGRESS — {idx}/{total} ({idx*100//total}%)")

        if mode == "init":
            logger.info("INIT — upgrading column types from actual data")
            for table_name in loaded_tables:
                upgrade_column_types(engine, table_name, logger)
        elif new_cols_by_table:
            logger.info("DAILY — upgrading column types for new columns")
            for table_name, cols in new_cols_by_table.items():
                upgrade_column_types(engine, table_name, logger, cols=list(cols))

    finally:
        finish_run_log(engine, run_id, processed, skipped, errors)
        logger.info(f"Run finished — {processed} loaded, {skipped} skipped, {errors} errors")


def run_scripts(script_path: str | None = None):
    cfg = Config()
    engine = get_engine(cfg.db_url)

    script_dir = Path("script")
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    if script_path:
        scripts = [Path(script_path)]
    else:
        scripts = sorted(script_dir.glob("*.sql"))

    if not scripts:
        print("No SQL scripts found.")
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ok_count = err_count = 0

    for sql_file in scripts:
        sql = sql_file.read_text(encoding="utf-8").strip()
        if not sql:
            print(f"SKIP  {sql_file.name} — empty file")
            continue
        try:
            df = pd.read_sql(sql, engine)
            out_path = output_dir / f"{sql_file.stem}_{timestamp}.xlsx"
            df.to_excel(out_path, index=False, engine="openpyxl")
            print(f"OK    {sql_file.name} → {out_path} ({len(df)} rows)")
            ok_count += 1
        except Exception as e:
            print(f"ERR   {sql_file.name}: {e}")
            err_count += 1

    print(f"\nDone — {ok_count} exported, {err_count} errors")


def main():
    parser = argparse.ArgumentParser(description="CMS data pipeline loader")
    parser.add_argument("--mode", choices=["init", "daily", "run_script"], required=True,
                        help="init: load all files; daily: load changed files since last run; run_script: execute SQL scripts and export to Excel")
    parser.add_argument("--script", default=None,
                        help="(run_script mode) path to a specific .sql file; omit to run all scripts in script/")
    args = parser.parse_args()

    if args.mode == "run_script":
        run_scripts(args.script)
    else:
        run(args.mode)


if __name__ == "__main__":
    main()

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

import argparse
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import pandas as pd

from loader.config import Config
from loader.db import (get_engine, ensure_database, create_metadata_tables,
                        get_last_run_time, insert_run_log, finish_run_log,
                        upsert_load_metadata, get_table_columns, drop_table,
                        upgrade_column_types)
from loader.logger import setup_logger
from loader.file_scanner import scan_all_files, scan_changed_files
from loader.excel_reader import read_excel
from loader.loader import load_file, normalize_col_name, build_table_schemas


def run(mode: str):
    cfg = Config()
    start_time = datetime.now(tz=timezone.utc)
    run_id_str = start_time.strftime("%Y%m%d_%H%M%S")
    logger = setup_logger(log_dir="logs", run_id=run_id_str)

    try:
        ensure_database(cfg.db_url)
        engine = get_engine(cfg.db_url, pool_size=5)
        create_metadata_tables(engine)
    except Exception as e:
        logger.critical(f"DB bootstrap failed: {e}")
        raise

    run_id = insert_run_log(engine, mode, start_time)
    logger.info(f"Run started — mode={mode} run_id={run_id}")

    processed = skipped = errors = 0
    loaded_tables: set[str] = set()
    new_cols_by_table: dict[str, set[str]] = defaultdict(set)

    try:
        if mode == "init":
            all_files = scan_all_files(cfg.folder_map)
            logger.info(f"Scanning: {len(all_files)} files found")

            table_names = {f["table_name"] for f in all_files}
            logger.info("INIT — dropping existing tables")
            for table_name in table_names:
                drop_table(engine, table_name)

            # Phase 1: build schemas from headers
            logger.info("INIT — Phase 1: building table schemas from file headers")
            files_to_load, n_skipped = build_table_schemas(engine, all_files, cfg, logger)
            skipped += n_skipped

            # Phase 2: parallel bulk load
            total = len(files_to_load)
            logger.info(f"INIT — Phase 2: loading {total} files (3 workers)")

            counter_lock = threading.Lock()
            completed_count = 0

            def load_one(f: dict) -> dict:
                path = f["file_path"]
                rel = f["rel_path"]
                table = f["table_name"]
                header = cfg.table_header_map.get(table, 0)
                df, read_err = read_excel(path, header=header)
                if read_err:
                    logger.warning(f"SKIP_FILE — {rel} — cannot read: {read_err}")
                    upsert_load_metadata(engine, rel, table, 0, "failed")
                    return {"rel": rel, "table": table, "outcome": "skip"}
                try:
                    stats = load_file(engine, df, table, rel, logger)
                    logger.info(f"LOADED — {rel} — {stats['loaded']} rows ({stats['skipped']} skipped)")
                    return {"rel": rel, "table": table, "outcome": "ok"}
                except Exception as e:
                    logger.error(f"ERROR — {rel} — {e}")
                    upsert_load_metadata(engine, rel, table, 0, "failed")
                    return {"rel": rel, "table": table, "outcome": "error"}

            # as_completed is consumed on the main thread — no data race on
            # processed/skipped/errors/loaded_tables; counter_lock guards completed_count
            # only because pct must be consistent with the logged value.
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = {executor.submit(load_one, f): f for f in files_to_load}
                for future in as_completed(futures):
                    result = future.result()
                    with counter_lock:
                        completed_count += 1
                        pct = completed_count * 100 // total if total else 100
                    logger.info(f"PROGRESS — {completed_count}/{total} ({pct}%)")
                    if result["outcome"] == "ok":
                        processed += 1
                        loaded_tables.add(result["table"])
                    elif result["outcome"] == "skip":
                        skipped += 1
                    else:
                        errors += 1

            # Phase 3: upgrade column types
            logger.info("INIT — Phase 3: upgrading column types")
            for table_name in loaded_tables:
                upgrade_column_types(engine, table_name, logger)

        else:  # daily
            last_run = get_last_run_time(engine)
            if last_run is None:
                logger.info("No previous run found, scanning all files")
                files = scan_all_files(cfg.folder_map)
            else:
                if last_run.tzinfo is None:
                    last_run = last_run.replace(tzinfo=timezone.utc)
                files = scan_changed_files(cfg.folder_map, last_run)

            logger.info(f"Scanning: {len(files)} files to process")
            total = len(files)

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
                    logger.info(f"PROGRESS — {idx}/{total} ({idx*100//total if total else 100}%)")
                    continue

                existing = get_table_columns(engine, table)
                norm_df_cols = {normalize_col_name(c) for c in df.columns}
                schema_cols = [c for c in existing if c not in ("source_file", "uuid")]
                missing = [c for c in schema_cols if c not in norm_df_cols]
                if missing:
                    logger.info(f"MISSING_COLS — {rel} — {missing} will be NULL")

                new_cols = [c for c in norm_df_cols if c not in existing]

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

            if new_cols_by_table:
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

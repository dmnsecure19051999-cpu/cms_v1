import logging
import sys
from datetime import datetime
from pathlib import Path

def setup_logger(log_dir: str = "logs", run_id: str = "") -> logging.Logger:
    Path(log_dir).mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = Path(log_dir) / f"{ts}_{run_id}.log"

    fmt = "[%(asctime)s] %(levelname)-5s %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    logger = logging.getLogger(f"cms.{run_id}")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    fh = logging.FileHandler(filename, encoding="utf-8")
    fh.setFormatter(logging.Formatter(fmt, datefmt))
    logger.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(logging.Formatter(fmt, datefmt))
    logger.addHandler(sh)

    return logger

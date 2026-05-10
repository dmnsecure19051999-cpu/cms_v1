from pathlib import Path

def test_logger_creates_log_file(tmp_path):
    from loader.logger import setup_logger
    log = setup_logger(log_dir=str(tmp_path), run_id="test123")
    log.info("hello")
    files = list(tmp_path.glob("*.log"))
    assert len(files) == 1

def test_logger_formats_message(tmp_path):
    from loader.logger import setup_logger
    log = setup_logger(log_dir=str(tmp_path), run_id="test123")
    log.warning("SKIP_FILE — somefile.xlsx — missing columns: ['id']")
    content = list(tmp_path.glob("*.log"))[0].read_text()
    assert "SKIP_FILE" in content
    assert "somefile.xlsx" in content

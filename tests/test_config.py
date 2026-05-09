import os
import pytest
from unittest.mock import patch

def test_config_loads_data_dir():
    with patch.dict(os.environ, {
        "DATA_DIR": "/tmp/cms",
        "DB_HOST": "localhost", "DB_PORT": "1433",
        "DB_NAME": "cms_db", "DB_USER": "sa", "DB_PASSWORD": "pass"
    }):
        from loader.config import Config
        cfg = Config()
        assert cfg.data_dir == "/tmp/cms"

def test_config_folder_table_mapping():
    with patch.dict(os.environ, {
        "DATA_DIR": "/tmp/cms",
        "DB_HOST": "localhost", "DB_PORT": "1433",
        "DB_NAME": "cms_db", "DB_USER": "sa", "DB_PASSWORD": "pass"
    }):
        from loader.config import Config
        cfg = Config()
        assert cfg.folder_map["cancel"] == "cancellation_bills"
        assert cfg.folder_map["customer_data"] == "customer_data"
        assert cfg.folder_map["revenue"] == "sales_revenue"

def test_config_db_url():
    with patch.dict(os.environ, {
        "DATA_DIR": "/tmp/cms",
        "DB_HOST": "localhost", "DB_PORT": "1433",
        "DB_NAME": "cms_db", "DB_USER": "sa", "DB_PASSWORD": "pass"
    }):
        from loader.config import Config
        cfg = Config()
        assert "localhost" in cfg.db_url
        assert "cms_db" in cfg.db_url

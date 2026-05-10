import os
import pytest
from unittest.mock import patch

BASE_ENV = {
    "CANCEL_DIR": "/tmp/cms/cancel",
    "CUSTOMER_DATA_DIR": "/tmp/cms/customer_data",
    "REVENUE_DIR": "/tmp/cms/revenue",
    "DB_HOST": "localhost", "DB_PORT": "1433",
    "DB_NAME": "cms_db", "DB_USER": "sa", "DB_PASSWORD": "pass",
}

def test_config_folder_table_mapping():
    with patch.dict(os.environ, BASE_ENV):
        from loader.config import Config
        cfg = Config()
        assert cfg.folder_map["/tmp/cms/cancel"] == "cancellation_bills"
        assert cfg.folder_map["/tmp/cms/customer_data"] == "customer_data"
        assert cfg.folder_map["/tmp/cms/revenue"] == "sales_revenue"

def test_config_db_url():
    with patch.dict(os.environ, BASE_ENV):
        from loader.config import Config
        cfg = Config()
        assert "localhost" in cfg.db_url
        assert "cms_db" in cfg.db_url

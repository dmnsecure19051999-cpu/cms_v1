import os
from urllib.parse import quote_plus
from dotenv import load_dotenv

class Config:
    def __init__(self):
        load_dotenv()
        self.db_host = os.environ["DB_HOST"]
        self.db_port = os.environ.get("DB_PORT", "5432")
        self.db_name = os.environ["DB_NAME"]
        self.db_user = os.environ.get("DB_USER", "")
        self.db_password = os.environ.get("DB_PASSWORD", "")
        self.folder_map = {
            os.environ["CANCEL_DIR"]: "cancellation_bills",
            os.environ["CUSTOMER_DATA_DIR"]: "customer_data",
            os.environ["REVENUE_DIR"]: "sales_revenue",
        }

    @property
    def db_url(self):
        return (
            f"postgresql+psycopg2://{quote_plus(self.db_user)}:{quote_plus(self.db_password)}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

import os
from dotenv import load_dotenv

class Config:
    def __init__(self):
        load_dotenv()
        self.data_dir = os.environ["DATA_DIR"]
        self.db_host = os.environ["DB_HOST"]
        self.db_port = os.environ.get("DB_PORT", "1433")
        self.db_name = os.environ["DB_NAME"]
        self.db_user = os.environ["DB_USER"]
        self.db_password = os.environ["DB_PASSWORD"]
        self.folder_map = {
            "cancel": "cancellation_bills",
            "customer_data": "customer_data",
            "revenue": "sales_revenue",
        }

    @property
    def db_url(self):
        return (
            f"mssql+pyodbc://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
            f"?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes"
        )

import os
from dotenv import load_dotenv
load_dotenv()

API_TOKEN = os.getenv("BOT_TOKEN")
DB_FILE = os.getenv("DB_PATH", "bot_database.db")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(",")))
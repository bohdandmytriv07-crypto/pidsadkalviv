import os
from dotenv import load_dotenv
load_dotenv()

API_TOKEN = os.getenv("BOT_TOKEN")
DB_FILE = os.getenv("DB_PATH", "bot_database.db")
env_admins = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(id_str) for id_str in env_admins.split(",") if id_str.strip().isdigit()]
SUPPORT_CHANNEL_ID = -1003727374942
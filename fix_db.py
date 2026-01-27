import sqlite3
import os
from datetime import datetime

DB_FILE = "bot_database.db"

def fix_database_schema():
    if not os.path.exists(DB_FILE):
        print(f"❌ Помилка: Файл {DB_FILE} не знайдено!")
        return

    print(f"🔧 Лікування бази даних: {DB_FILE}...")
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. Список колонок, які треба додати
    columns_to_check = [
        ("users", "rating_driver", "REAL DEFAULT 5.0"),
        ("users", "rating_pass", "REAL DEFAULT 5.0"),
        ("users", "created_at", f"DATETIME DEFAULT '{now_str}'"),
        ("users", "last_active", f"DATETIME DEFAULT '{now_str}'"),
        ("trips", "description", "TEXT DEFAULT ''"),
        ("bookings", "created_at", f"DATETIME DEFAULT '{now_str}'"),
        # 🔥 ВИПРАВЛЕННЯ ПОМИЛКИ ЧАТУ:
        ("chat_history", "message", "TEXT") 
    ]

    print("\n🚀 Перевірка колонок...")
    for table, column, dtype in columns_to_check:
        try:
            cursor.execute(f"PRAGMA table_info({table})")
            existing = [info[1] for info in cursor.fetchall()]
            
            if column not in existing:
                print(f"➕ Додаю колонку '{column}' в '{table}'...")
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {dtype}")
            else:
                print(f"✅ Колонка '{column}' вже є в '{table}'.")
                
        except sqlite3.OperationalError as e:
            print(f"⚠️ Проблема з таблицею {table}: {e}")

    conn.commit()
    conn.close()
    print("\n🏁 База даних вилікувана! Запускайте main.py")

if __name__ == "__main__":
    fix_database_schema()
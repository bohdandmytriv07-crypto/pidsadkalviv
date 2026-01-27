import sqlite3
import datetime
import os

# Ім'я файлу бази даних
DB_FILE = "bot_database.db"

def fix_migration():
    if not os.path.exists(DB_FILE):
        print(f"❌ Файл {DB_FILE} не знайдено.")
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Отримуємо поточний час, щоб записати його в старі рядки
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print("🔧 Починаємо виправлення бази...")

    # --- 1. Додаємо join_date (без default) ---
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN join_date TEXT")
        print("✅ Додано колонку join_date")
        # Заповнюємо старі записи поточним часом
        cursor.execute("UPDATE users SET join_date = ? WHERE join_date IS NULL", (now_str,))
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e):
            print("ℹ️ Колонка join_date вже існує")
        else:
            print(f"⚠️ Помилка join_date: {e}")

    # --- 2. Додаємо last_active (без default) ---
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN last_active TEXT")
        print("✅ Додано колонку last_active")
        # Заповнюємо старі записи поточним часом
        cursor.execute("UPDATE users SET last_active = ? WHERE last_active IS NULL", (now_str,))
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e):
            print("ℹ️ Колонка last_active вже існує")
        else:
            print(f"⚠️ Помилка last_active: {e}")

    conn.commit()
    conn.close()
    print("🏁 База виправлена! Можна запускати бота.")

if __name__ == "__main__":
    fix_migration()
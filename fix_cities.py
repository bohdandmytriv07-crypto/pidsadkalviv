import sqlite3
import os

DB_FILE = "bot_database.db"

def fix_cities():
    if not os.path.exists(DB_FILE):
        print(f"❌ Файл {DB_FILE} не знайдено!")
        return

    print(f"🔧 Підключаюсь до {DB_FILE}...")
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    try:
        # 1. Перевіряємо, які колонки є зараз
        cursor.execute("PRAGMA table_info(cities)")
        columns = [info[1] for info in cursor.fetchall()]
        print(f"🧐 Поточні колонки в cities: {columns}")

        # 2. Якщо немає search_count - додаємо
        if "search_count" not in columns:
            print("➕ Додаю колонку 'search_count'...")
            cursor.execute("ALTER TABLE cities ADD COLUMN search_count INTEGER DEFAULT 1")
            conn.commit()
            print("✅ Успішно додано!")
        else:
            print("✅ Колонка 'search_count' вже є.")

    except Exception as e:
        print(f"❌ Помилка: {e}")
        # Якщо таблиці взагалі немає, створимо її
        if "no such table: cities" in str(e):
            print("⚠️ Таблиці cities немає. Створюю нову...")
            cursor.execute('''
                CREATE TABLE cities (
                    name TEXT PRIMARY KEY,
                    search_count INTEGER DEFAULT 1
                )
            ''')
            conn.commit()
            print("✅ Таблицю cities створено.")

    conn.close()
    print("\n🏁 Готово! Запускайте main.py")

if __name__ == "__main__":
    fix_cities()
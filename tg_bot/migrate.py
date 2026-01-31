import sqlite3
from config import DB_FILE

def migrate_db():
    print(f"🔧 Підключаюсь до {DB_FILE}...")
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    try:
        # Додаємо колонку reminded в таблицю bookings
        cursor.execute("ALTER TABLE bookings ADD COLUMN reminded INTEGER DEFAULT 0")
        print("✅ Успіх! Колонка 'reminded' додана в таблицю 'bookings'.")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e):
            print("ℹ️ Колонка 'reminded' вже існує. Нічого робити не треба.")
        else:
            print(f"❌ Помилка: {e}")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    migrate_db()
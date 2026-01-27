import sqlite3
from config import DB_FILE

def migrate_description():
    print(f"🔄 Додаю коментарі до поїздок у {DB_FILE}...")
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    try:
        # Додаємо колонку опису (текст, може бути пустим)
        cursor.execute("ALTER TABLE trips ADD COLUMN description TEXT DEFAULT ''")
        print("✅ Додано колонку description")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e):
            print("ℹ️ Колонка description вже існує")
        else:
            print(f"❌ Помилка: {e}")

    conn.commit()
    conn.close()
    print("🏁 Готово! Тепер водії можуть писати коментарі.")

if __name__ == "__main__":
    migrate_description()
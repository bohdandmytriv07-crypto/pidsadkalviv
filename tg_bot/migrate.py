import sqlite3
from config import DB_FILE

def migrate():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    print("🔄 Оновлення бази даних...")

    # 1. Для нагадувань (чи було надіслано нагадування)
    try:
        cursor.execute("ALTER TABLE bookings ADD COLUMN reminded INTEGER DEFAULT 0")
        print("✅ Додано колонку 'reminded' в bookings")
    except: print("ℹ️ Колонка 'reminded' вже є")

    # 2. Для коментарів у відгуках
    try:
        cursor.execute("ALTER TABLE ratings ADD COLUMN comment TEXT DEFAULT ''")
        print("✅ Додано колонку 'comment' в ratings")
    except: print("ℹ️ Колонка 'comment' вже є")

    conn.commit()
    conn.close()
    print("🏁 Міграція завершена!")

if __name__ == "__main__":
    migrate()
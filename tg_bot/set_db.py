import sqlite3
from config import DB_FILE
from database import init_db

INITIAL_CITIES = [
    "Київ", "Львів", "Одеса", "Дніпро", "Харків", 
    "Запоріжжя", "Вінниця", "Луцьк", "Житомир", 
    "Ужгород", "Івано-Франківськ", "Кропивницький", 
    "Миколаїв", "Полтава", "Рівне", "Суми", 
    "Тернопіль", "Херсон", "Хмельницький", 
    "Черкаси", "Чернівці", "Чернігів", "Кривий Ріг", 
    "Маріуполь", "Біла Церква", "Бровари", "Кам'янець-Подільський",
    "Умань", "Мукачево", "Дрогобич"
]

def seed_data():
    """Заповнює базу початковими даними."""
    print("⏳ Підключення до бази...")
    
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        
        count = cursor.execute("SELECT COUNT(*) FROM cities").fetchone()[0]
        if count > 0:
            print(f"⚠️ База вже містить {count} міст. Пропускаю наповнення.")
            return

        print("🚀 Додаю міста...")
        for city in INITIAL_CITIES:
            try:
                # 🔥 ВИПРАВЛЕНО: popularity -> search_count
                cursor.execute("INSERT INTO cities (name, search_count) VALUES (?, 1)", (city,))
            except sqlite3.IntegrityError:
                pass 
        
        conn.commit()
        print(f"✅ Успішно додано {len(INITIAL_CITIES)} міст!")

if __name__ == "__main__":
    init_db()
    seed_data()
    print("🏁 Налаштування бази завершено. Можна запускати бота!")
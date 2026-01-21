import sqlite3
from datetime import datetime
import pytz

# 🔥 Єдине джерело правди про назву файлу
from config import DB_FILE 

# ==========================================
# ⚙️ НАЛАШТУВАННЯ ПІДКЛЮЧЕННЯ
# ==========================================

def get_connection():
    """
    Створює підключення до БД з оптимізацією.
    """
    conn = sqlite3.connect(DB_FILE)
    
    # WAL Mode: пришвидшення запису/читання
    conn.execute("PRAGMA journal_mode=WAL;") 
    
    # Підтримка зовнішніх ключів
    conn.execute("PRAGMA foreign_keys=ON;")
    
    # Доступ до колонок по імені
    conn.row_factory = sqlite3.Row 
    
    return conn

# Аліас для сумісності
def get_db():
    return get_connection()


# ==========================================
# 🛠 ІНІЦІАЛІЗАЦІЯ ТАБЛИЦЬ
# ==========================================

def init_db():
    """Створює всі необхідні таблиці при першому запуску."""
    conn = get_connection()
    cursor = conn.cursor()
    
    # 1. Користувачі (з новою колонкою terms_accepted)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            phone TEXT,
            model TEXT DEFAULT '-',
            body TEXT DEFAULT '-',
            color TEXT DEFAULT '-',
            number TEXT DEFAULT '-',
            is_banned INTEGER DEFAULT 0,
            terms_accepted INTEGER DEFAULT 0  -- 0 = ні, 1 = так
        )
    ''')

    # 2. Поїздки
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trips (
            id TEXT PRIMARY KEY,
            user_id INTEGER,
            origin TEXT,
            destination TEXT,
            date TEXT,
            time TEXT,
            seats_total INTEGER,
            seats_taken INTEGER DEFAULT 0,
            price INTEGER,
            status TEXT DEFAULT 'active',
            is_notified INTEGER DEFAULT 0,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
    ''')

    # 3. Бронювання
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trip_id TEXT,
            passenger_id INTEGER,
            FOREIGN KEY(trip_id) REFERENCES trips(id),
            FOREIGN KEY(passenger_id) REFERENCES users(user_id)
        )
    ''')

    # 4. Історія пошуку
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS search_history (
            user_id INTEGER,
            origin TEXT,
            destination TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 5. Підписки
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS subscriptions (
            user_id INTEGER,
            origin TEXT,
            destination TEXT,
            date TEXT
        )
    ''')

    # 6. Міста
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cities (
            name TEXT PRIMARY KEY,
            popularity INTEGER DEFAULT 1
        )
    ''')

    # 7. Активні чати
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS active_chats (
            user_id INTEGER PRIMARY KEY,
            partner_id INTEGER
        )
    ''')

    # 8. Логи повідомлень (для видалення)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_messages (
            user_id INTEGER,
            message_id INTEGER
        )
    ''')

    # 9. Історія повідомлень (текст)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER,
            receiver_id INTEGER,
            message_text TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()
    conn.close()


# ==========================================
# 👤 КОРИСТУВАЧІ & УГОДА
# ==========================================

def save_user(user_id, name, phone, model="-", body="-", color="-", number="-"):
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    exist = cursor.fetchone()
    
    if exist:
        new_model = model if model != "-" else exist['model']
        new_body = body if body != "-" else exist['body']
        new_color = color if color != "-" else exist['color']
        new_number = number if number != "-" else exist['number']
        new_phone = phone if phone != "-" else exist['phone']
        
        cursor.execute('''
            UPDATE users SET name=?, phone=?, model=?, body=?, color=?, number=?
            WHERE user_id=?
        ''', (name, new_phone, new_model, new_body, new_color, new_number, user_id))
    else:
        cursor.execute('''
            INSERT INTO users (user_id, name, phone, model, body, color, number, terms_accepted)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
        ''', (user_id, name, phone, model, body, color, number))
        
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def is_user_banned(user_id):
    u = get_user(user_id)
    return u['is_banned'] == 1 if u else False

def check_terms_status(user_id: int) -> bool:
    """Перевіряє, чи погодився користувач з правилами."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT terms_accepted FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row and row['terms_accepted'] == 1:
        return True
    return False

def accept_terms(user_id: int, full_name: str):
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if cursor.fetchone():
        cursor.execute("UPDATE users SET terms_accepted = 1 WHERE user_id = ?", (user_id,))
    else:
        cursor.execute('''
            INSERT INTO users (user_id, name, phone, terms_accepted)
            VALUES (?, ?, '-', 1)
        ''', (user_id, full_name))
        
    conn.commit()
    conn.close()


# ==========================================
# 🚗 ВОДІЙ: ФУНКЦІОНАЛ
# ==========================================

def create_trip(trip_id, user_id, origin, destination, date, time, seats, price):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO trips (id, user_id, origin, destination, date, time, seats_total, price)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (trip_id, user_id, origin, destination, date, time, seats, price))
    conn.commit()
    conn.close()

def get_last_driver_trip(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trips WHERE user_id = ? ORDER BY rowid DESC LIMIT 1", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_driver_active_trips(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trips WHERE user_id = ? AND status='active'", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_trip_passengers(trip_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT u.name, u.phone, u.user_id, b.id as booking_id 
        FROM bookings b
        JOIN users u ON b.passenger_id = u.user_id
        WHERE b.trip_id = ?
    ''', (trip_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def kick_passenger(booking_id, driver_id):
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT b.passenger_id, t.origin, t.destination, t.date, t.time, t.id
        FROM bookings b
        JOIN trips t ON b.trip_id = t.id
        WHERE b.id = ? AND t.user_id = ?
    ''', (booking_id, driver_id))
    row = cursor.fetchone()
    
    if row:
        cursor.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
        cursor.execute("UPDATE trips SET seats_taken = seats_taken - 1 WHERE id = ?", (row['id'],))
        conn.commit()
        conn.close()
        return dict(row)
    
    conn.close()
    return None

def cancel_trip_full(trip_id, driver_id):
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM trips WHERE id = ? AND user_id = ?", (trip_id, driver_id))
    trip = cursor.fetchone()
    
    if trip:
        cursor.execute("SELECT passenger_id FROM bookings WHERE trip_id = ?", (trip_id,))
        passengers = [r[0] for r in cursor.fetchall()]
        
        cursor.execute("DELETE FROM bookings WHERE trip_id = ?", (trip_id,))
        cursor.execute("UPDATE trips SET status='cancelled' WHERE id = ?", (trip_id,))
        conn.commit()
        conn.close()
        return dict(trip), passengers
        
    conn.close()
    return None, []


# ==========================================
# 🚶 ПАСАЖИР: ПОШУК ТА БРОНЬ
# ==========================================

def search_trips(origin, destination, date, viewer_id):
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT t.*, u.name as driver_name, u.model, u.color, u.user_id 
        FROM trips t
        JOIN users u ON t.user_id = u.user_id
        WHERE t.origin = ? AND t.destination = ? AND t.date = ? 
        AND t.status = 'active' AND t.seats_taken < t.seats_total
        AND t.user_id != ?
    ''', (origin, destination, date, viewer_id))
    
    rows = cursor.fetchall()
    conn.close()
    return rows

def add_booking(trip_id, passenger_id):
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT seats_taken, seats_total, user_id FROM trips WHERE id = ?", (trip_id,))
    trip = cursor.fetchone()
    
    if not trip:
        conn.close()
        return False, "Поїздку не знайдено."
        
    taken, total, driver_id = trip
    if taken >= total:
        conn.close()
        return False, "Місць немає."
        
    if driver_id == passenger_id:
        conn.close()
        return False, "Ви водій цієї поїздки."

    cursor.execute("SELECT id FROM bookings WHERE trip_id = ? AND passenger_id = ?", (trip_id, passenger_id))
    if cursor.fetchone():
        conn.close()
        return False, "Ви вже забронювали місце."

    try:
        cursor.execute("INSERT INTO bookings (trip_id, passenger_id) VALUES (?, ?)", (trip_id, passenger_id))
        cursor.execute("UPDATE trips SET seats_taken = seats_taken + 1 WHERE id = ?", (trip_id,))
        conn.commit()
        conn.close()
        return True, "OK"
    except Exception as e:
        conn.close()
        return False, f"Помилка: {e}"

def get_user_bookings(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT b.id, t.origin, t.destination, t.date, t.time, t.price, 
               u.name as driver_name, u.phone as driver_phone, t.user_id as driver_id, t.id as trip_id
        FROM bookings b
        JOIN trips t ON b.trip_id = t.id
        JOIN users u ON t.user_id = u.user_id
        WHERE b.passenger_id = ? AND t.status = 'active'
    ''', (user_id,))
    
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_booking(booking_id, passenger_id):
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT t.origin, t.destination, t.date, t.time, t.user_id as driver_id, t.id as trip_id, u.name as pass_name
        FROM bookings b
        JOIN trips t ON b.trip_id = t.id
        JOIN users u ON u.user_id = ?
        WHERE b.id = ? AND b.passenger_id = ?
    ''', (passenger_id, booking_id, passenger_id))
    row = cursor.fetchone()
    
    if row:
        cursor.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
        cursor.execute("UPDATE trips SET seats_taken = seats_taken - 1 WHERE id = ?", (row['trip_id'],))
        conn.commit()
        info = {
            'origin': row['origin'], 'destination': row['destination'],
            'date': row['date'], 'time': row['time'],
            'driver_id': row['driver_id'], 'passenger_name': row['pass_name']
        }
        conn.close()
        return info
        
    conn.close()
    return None

def get_trip_details(trip_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT t.*, u.name, u.phone, u.model, u.number, u.color
        FROM trips t
        JOIN users u ON t.user_id = u.user_id
        WHERE t.id = ?
    ''', (trip_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


# ==========================================
# 🏙️ ДОДАТКОВО: ІСТОРІЯ, МІСТА
# ==========================================

def get_recent_searches(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT origin, destination FROM search_history WHERE user_id = ? ORDER BY rowid DESC LIMIT 3", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def save_search_history(user_id, origin, dest):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO search_history (user_id, origin, destination) VALUES (?, ?, ?)", (user_id, origin, dest))
    conn.commit()
    conn.close()

def get_user_history(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT t.origin, t.destination, t.date, t.time, t.price, u.name as driver_name
        FROM bookings b
        JOIN trips t ON b.trip_id = t.id
        JOIN users u ON t.user_id = u.user_id
        WHERE b.passenger_id = ? AND t.status = 'finished'
    ''', (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_subscription(user_id, origin, destination, date):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO subscriptions VALUES (?, ?, ?, ?)", (user_id, origin, destination, date))
    conn.commit()
    conn.close()

def get_subscribers_for_trip(origin, destination, date):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM subscriptions WHERE origin=? AND destination=? AND date=?", (origin, destination, date))
    rows = cursor.fetchall()
    if rows:
        cursor.execute("DELETE FROM subscriptions WHERE origin=? AND destination=? AND date=?", (origin, destination, date))
        conn.commit()
    conn.close()
    return [r[0] for r in rows]

def add_or_update_city(name):
    if len(name) < 2: return
    clean = name.strip().title()
    conn = get_connection()
    try:
        conn.execute("INSERT OR IGNORE INTO cities (name) VALUES (?)", (clean,))
        conn.execute("UPDATE cities SET popularity = popularity + 1 WHERE name = ?", (clean,))
        conn.commit()
    except: pass
    conn.close()

def get_all_cities_names():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM cities ORDER BY popularity DESC")
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows]


# ==========================================
# 💬 ЧАТ (ЗБЕРЕЖЕННЯ ПОВІДОМЛЕНЬ)
# ==========================================

def set_active_chat(user_id, partner_id):
    conn = get_connection()
    conn.execute("INSERT OR REPLACE INTO active_chats (user_id, partner_id) VALUES (?, ?)", (user_id, partner_id))
    conn.commit()
    conn.close()

def get_active_chat_partner(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT partner_id FROM active_chats WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def delete_active_chat(user_id):
    conn = get_connection()
    conn.execute("DELETE FROM active_chats WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def save_chat_msg(user_id, message_id):
    conn = get_connection()
    conn.execute('INSERT INTO chat_messages (user_id, message_id) VALUES (?, ?)', (user_id, message_id))
    conn.commit()
    conn.close()

def get_and_clear_chat_msgs(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT message_id FROM chat_messages WHERE user_id = ?', (user_id,))
    rows = cursor.fetchall()
    cursor.execute('DELETE FROM chat_messages WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()
    return [row[0] for row in rows]


# ==========================================
# 📜 ІСТОРІЯ ЧАТУ (TEXT)
# ==========================================

def save_message_to_history(sender_id, receiver_id, text):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO chat_history (sender_id, receiver_id, message_text) VALUES (?, ?, ?)", 
            (sender_id, receiver_id, text)
        )
        conn.commit()
    except: pass
    conn.close()

def get_chat_history_text(user_id, partner_id, limit=10):
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    query = """
        SELECT sender_id, message_text 
        FROM chat_history 
        WHERE (sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?)
        ORDER BY id DESC LIMIT ?
    """
    rows = cursor.execute(query, (user_id, partner_id, partner_id, user_id, limit)).fetchall()
    conn.close()
    
    if not rows:
        return None

    rows = rows[::-1]
    
    history_text = "📜 <b>Історія повідомлень:</b>\n"
    for row in rows:
        if row['sender_id'] == user_id:
            history_text += f"👤 Ви: {row['message_text']}\n"
        else:
            history_text += f"🚕 Співрозмовник: {row['message_text']}\n"
            
    return history_text + "➖➖➖➖➖➖➖➖\n"


# ==========================================
# 🔄 ФОНОВІ ЗАДАЧІ
# ==========================================

def mark_trip_notified(trip_id):
    conn = get_connection()
    conn.execute("UPDATE trips SET is_notified = 1 WHERE id = ?", (trip_id,))
    conn.commit()
    conn.close()

def finish_trip(trip_id):
    conn = get_connection()
    conn.execute("UPDATE trips SET status = 'finished' WHERE id = ?", (trip_id,))
    conn.commit()
    conn.close()
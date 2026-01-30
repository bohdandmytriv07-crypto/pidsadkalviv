import sqlite3
from datetime import datetime
from config import DB_FILE

# ==========================================
# 🔌 ПІДКЛЮЧЕННЯ
# ==========================================

def get_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row  # Дозволяє звертатись до полів за назвою (row['id'])
    return conn

def init_db():
    conn = get_connection()
    # 🔥 Вмикаємо WAL режим для швидкості
    conn.execute("PRAGMA journal_mode=WAL;") 
    conn.execute("PRAGMA synchronous=NORMAL;")
    
    # 1. Користувачі
    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            name TEXT,
            phone TEXT DEFAULT '-',
            model TEXT DEFAULT '-',
            number TEXT DEFAULT '-',
            color TEXT DEFAULT '-',
            rating_driver REAL DEFAULT 5.0,
            rating_pass REAL DEFAULT 5.0,
            is_banned INTEGER DEFAULT 0,
            terms_accepted INTEGER DEFAULT 0,
            ref_source TEXT,
            is_blocked_bot INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_active DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 2. Поїздки
    conn.execute('''
        CREATE TABLE IF NOT EXISTS trips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            origin TEXT,
            destination TEXT,
            date TEXT,
            time TEXT,
            seats_total INTEGER,
            seats_taken INTEGER DEFAULT 0,
            price INTEGER,
            status TEXT DEFAULT 'active',
            description TEXT DEFAULT '' 
        )
    ''')
    # Індекси для пошуку
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trips_search ON trips(origin, destination, date, status)")

    # 3. Бронювання
    conn.execute('''
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trip_id INTEGER,
            passenger_id INTEGER,
            status TEXT DEFAULT 'active',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 4. Історія пошуку
    conn.execute('''
        CREATE TABLE IF NOT EXISTS search_history (
            user_id INTEGER,
            origin TEXT,
            destination TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 5. Чат (історія)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER,
            receiver_id INTEGER,
            message TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            is_read INTEGER DEFAULT 0
        )
    ''')

    # 6. Активні сесії чатів
    conn.execute('''
        CREATE TABLE IF NOT EXISTS active_chats (
            user_id INTEGER PRIMARY KEY,
            partner_id INTEGER
        )
    ''')

    # 7. Очистка інтерфейсу (повідомлення для видалення)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS interface_cleanup (
            user_id INTEGER,
            message_id INTEGER
        )
    ''')

    # 8. Інші таблиці
    conn.execute('CREATE TABLE IF NOT EXISTS cities (name TEXT PRIMARY KEY, search_count INTEGER DEFAULT 1)')
    conn.execute('CREATE TABLE IF NOT EXISTS subscriptions (user_id INTEGER, origin TEXT, destination TEXT, date TEXT)')
    conn.execute('CREATE TABLE IF NOT EXISTS ratings (id INTEGER PRIMARY KEY AUTOINCREMENT, from_user_id INTEGER, to_user_id INTEGER, trip_id INTEGER, role TEXT, score INTEGER, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)')

    conn.commit()
    conn.close()

# ==========================================
# 👤 КОРИСТУВАЧІ
# ==========================================

def get_user(user_id):
    conn = get_connection()
    user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(user) if user else None

def save_user(user_id, name, username, phone=None, model='-', number='-', color='-', ref_source=None):
    conn = get_connection()
    if get_user(user_id):
        # Оновлення
        updates = ["name=?, username=?, last_active=CURRENT_TIMESTAMP"]
        params = [name, username]
        
        if phone: 
            updates.append("phone=?")
            params.append(phone)
        if model != '-': 
            updates.append("model=?")
            params.append(model)
        if number != '-': 
            updates.append("number=?")
            params.append(number)
        if color != '-': 
            updates.append("color=?")
            params.append(color)
        if ref_source:
             updates.append("ref_source = COALESCE(ref_source, ?)")
             params.append(ref_source)
        
        params.append(user_id)
        sql = f"UPDATE users SET {', '.join(updates)} WHERE user_id=?"
        conn.execute(sql, params)
    else:
        # Створення
        conn.execute('''
            INSERT INTO users (user_id, username, name, phone, ref_source) 
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, username, name, phone if phone else '-', ref_source))
    conn.commit()
    conn.close()

def update_user_activity(user_id, username, name):
    conn = get_connection()
    conn.execute('''
        INSERT INTO users (user_id, username, name, phone) 
        VALUES (?, ?, ?, '-')
        ON CONFLICT(user_id) DO UPDATE SET 
            last_active = CURRENT_TIMESTAMP,
            username = excluded.username,
            name = excluded.name
    ''', (user_id, username, name))
    conn.commit()
    conn.close()

def is_user_banned(user_id):
    user = get_user(user_id)
    return user['is_banned'] == 1 if user else False

def set_user_blocked_bot(user_id, is_blocked):
    conn = get_connection()
    conn.execute("UPDATE users SET is_blocked_bot = ? WHERE user_id = ?", (1 if is_blocked else 0, user_id))
    conn.commit()
    conn.close()

def ban_user_by_id(user_id, reason="Admin Ban"):
    conn = get_connection()
    conn.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (user_id,))
    # Скасовуємо активні поїздки та бронювання
    conn.execute("UPDATE trips SET status = 'cancelled' WHERE user_id = ? AND status = 'active'", (user_id,))
    conn.execute("UPDATE bookings SET status = 'cancelled' WHERE passenger_id = ? AND status = 'active'", (user_id,))
    conn.commit()
    conn.close()

def check_terms_status(user_id):
    user = get_user(user_id)
    return user['terms_accepted'] == 1 if user else False

def accept_terms(user_id, full_name):
    conn = get_connection()
    conn.execute("UPDATE users SET terms_accepted = 1, name = ? WHERE user_id = ?", (full_name, user_id))
    conn.commit()
    conn.close()

# ==========================================
# 🚗 ПОЇЗДКИ (TRIPS)
# ==========================================

def create_trip(user_id, origin, destination, date, time, seats, price, description=""):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO trips (user_id, origin, destination, date, time, seats_total, price, description) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, origin, destination, date, time, seats, price, description))
    trip_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return trip_id

def get_trip_details(trip_id):
    conn = get_connection()
    row = conn.execute('''
        SELECT t.*, u.name, u.phone, u.rating_driver, u.model, u.color, u.username
        FROM trips t JOIN users u ON t.user_id = u.user_id WHERE t.id = ?
    ''', (trip_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def get_active_driver_trips(user_id):
    """Повертає список активних поїздок водія (для перевірки дублікатів)."""
    conn = get_connection()
    rows = conn.execute("SELECT date, time FROM trips WHERE user_id = ? AND status = 'active'", (user_id,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_driver_active_trips_full(user_id):
    """Для меню 'Мої поїздки'."""
    conn = get_connection()
    rows = conn.execute("SELECT * FROM trips WHERE user_id = ? AND status = 'active' ORDER BY date, time", (user_id,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_last_driver_trip(user_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM trips WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def finish_trip(trip_id):
    conn = get_connection()
    conn.execute("UPDATE trips SET status = 'finished' WHERE id = ?", (trip_id,))
    conn.commit()
    conn.close()

def delete_trip(trip_id):
    """Повне скасування поїздки водієм."""
    conn = get_connection()
    # Отримуємо ID пасажирів для сповіщення
    passengers = conn.execute("SELECT passenger_id FROM bookings WHERE trip_id = ? AND status = 'active'", (trip_id,)).fetchall()
    
    conn.execute("UPDATE trips SET status = 'cancelled' WHERE id = ?", (trip_id,))
    conn.execute("UPDATE bookings SET status = 'cancelled' WHERE trip_id = ?", (trip_id,))
    conn.commit()
    conn.close()
    
    return [p['passenger_id'] for p in passengers]

# ==========================================
# 🔍 ПОШУК ТА ПАГІНАЦІЯ
# ==========================================

def search_trips_page(origin, destination, date, viewer_id, limit, offset):
    conn = get_connection()
    
    # Отримуємо поїздки
    rows = conn.execute('''
        SELECT t.*, u.name as driver_name, u.rating_driver, u.model, u.color, u.user_id
        FROM trips t
        JOIN users u ON t.user_id = u.user_id
        WHERE t.origin = ? AND t.destination = ? AND t.date = ? 
          AND t.status = 'active' AND t.seats_taken < t.seats_total
          AND t.user_id != ?
        ORDER BY t.time ASC
        LIMIT ? OFFSET ?
    ''', (origin, destination, date, viewer_id, limit, offset)).fetchall()
    
    # Рахуємо загальну кількість
    count = conn.execute('''
        SELECT COUNT(*)
        FROM trips t
        WHERE t.origin = ? AND t.destination = ? AND t.date = ? 
          AND t.status = 'active' AND t.seats_taken < t.seats_total
          AND t.user_id != ?
    ''', (origin, destination, date, viewer_id)).fetchone()[0]
    
    conn.close()
    return [dict(row) for row in rows], count

# ==========================================
# 🎫 БРОНЮВАННЯ (З ОБМЕЖЕННЯМИ)
# ==========================================

def get_user_active_bookings_count(user_id):
    """Рахує активні бронювання для захисту від спаму."""
    conn = get_connection()
    count = conn.execute("SELECT count(*) FROM bookings WHERE passenger_id = ? AND status = 'active'", (user_id,)).fetchone()[0]
    conn.close()
    return count

def add_booking(trip_id, passenger_id):
    conn = get_connection()
    
    # Перевірка на повтор
    exist = conn.execute("SELECT id FROM bookings WHERE trip_id = ? AND passenger_id = ? AND status = 'active'", (trip_id, passenger_id)).fetchone()
    if exist: 
        conn.close()
        return False, "Ви вже забронювали місце."

    # Перевірка місць та статусу поїздки
    trip = conn.execute("SELECT seats_taken, seats_total, user_id, status FROM trips WHERE id = ?", (trip_id,)).fetchone()
    
    if not trip or trip['status'] != 'active':
        conn.close()
        return False, "Поїздка не активна."
    
    if trip['seats_taken'] >= trip['seats_total']:
        conn.close()
        return False, "Місць немає."
        
    if trip['user_id'] == passenger_id:
        conn.close()
        return False, "Не можна бронювати у себе."

    conn.execute("INSERT INTO bookings (trip_id, passenger_id) VALUES (?, ?)", (trip_id, passenger_id))
    conn.execute("UPDATE trips SET seats_taken = seats_taken + 1 WHERE id = ?", (trip_id,))
    conn.commit()
    conn.close()
    return True, "Success"

def get_user_bookings(user_id):
    conn = get_connection()
    rows = conn.execute('''
        SELECT b.id, b.trip_id, t.origin, t.destination, t.date, t.time, 
               u.name as driver_name, u.phone as driver_phone, t.user_id as driver_id
        FROM bookings b
        JOIN trips t ON b.trip_id = t.id
        JOIN users u ON t.user_id = u.user_id
        WHERE b.passenger_id = ? AND b.status = 'active'
        ORDER BY t.date ASC, t.time ASC
    ''', (user_id,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]

def delete_booking(booking_id, passenger_id):
    conn = get_connection()
    booking = conn.execute("SELECT trip_id FROM bookings WHERE id = ? AND passenger_id = ? AND status='active'", (booking_id, passenger_id)).fetchone()
    
    if not booking:
        conn.close()
        return None
        
    trip_id = booking['trip_id']
    trip = conn.execute("SELECT t.user_id as driver_id, u.name as passenger_name FROM trips t, users u WHERE t.id = ? AND u.user_id = ?", (trip_id, passenger_id)).fetchone()
    
    conn.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ?", (booking_id,))
    conn.execute("UPDATE trips SET seats_taken = seats_taken - 1 WHERE id = ?", (trip_id,))
    
    conn.commit()
    conn.close()
    return dict(trip)

def get_trip_passengers(trip_id):
    conn = get_connection()
    rows = conn.execute('''
        SELECT u.user_id, u.name, u.phone, u.username, b.id as booking_id 
        FROM bookings b JOIN users u ON b.passenger_id = u.user_id 
        WHERE b.trip_id = ? AND b.status = 'active'
    ''', (trip_id,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_passenger_history(user_id):
    conn = get_connection()
    rows = conn.execute('''
        SELECT t.origin, t.destination, t.date, t.price, u.name as driver_name
        FROM bookings b
        JOIN trips t ON b.trip_id = t.id
        JOIN users u ON t.user_id = u.user_id
        WHERE b.passenger_id = ? AND (t.status = 'finished' OR t.date < date('now'))
        ORDER BY t.date DESC LIMIT 10
    ''', (user_id,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]

# ==========================================
# 💬 ЧАТ & ОЧИСТКА
# ==========================================

def set_active_chat(user_id, partner_id):
    conn = get_connection()
    conn.execute("INSERT OR REPLACE INTO active_chats (user_id, partner_id) VALUES (?, ?)", (user_id, partner_id))
    conn.commit()
    conn.close()

def get_active_chat_partner(user_id):
    conn = get_connection()
    row = conn.execute("SELECT partner_id FROM active_chats WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return row['partner_id'] if row else None

def delete_active_chat(user_id):
    conn = get_connection()
    conn.execute("DELETE FROM active_chats WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def save_message_to_history(sender_id, receiver_id, text):
    conn = get_connection()
    conn.execute("INSERT INTO chat_history (sender_id, receiver_id, message) VALUES (?, ?, ?)", (sender_id, receiver_id, text))
    conn.commit()
    conn.close()

def get_chat_history_text(user1, user2):
    conn = get_connection()
    rows = conn.execute('''
        SELECT sender_id, message FROM chat_history 
        WHERE (sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?)
        ORDER BY timestamp DESC LIMIT 10
    ''', (user1, user2, user2, user1)).fetchall()
    conn.close()
    
    if not rows: return None
    rows = rows[::-1]
    
    text = "📜 <b>Останні повідомлення:</b>\n\n"
    for r in rows:
        sender = "Ви" if r['sender_id'] == user1 else "Співрозмовник"
        text += f"▫️ <b>{sender}:</b> {r['message']}\n"
    return text + "\n➖➖➖➖➖➖\n"

def save_chat_msg(user_id, message_id):
    conn = get_connection()
    conn.execute("INSERT INTO interface_cleanup (user_id, message_id) VALUES (?, ?)", (user_id, message_id))
    conn.commit()
    conn.close()

def get_and_clear_chat_msgs(user_id):
    conn = get_connection()
    rows = conn.execute("SELECT message_id FROM interface_cleanup WHERE user_id = ?", (user_id,)).fetchall()
    conn.execute("DELETE FROM interface_cleanup WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    return [r['message_id'] for r in rows]

# ==========================================
# ⭐ РЕЙТИНГ & УТИЛІТИ
# ==========================================

def format_rating(avg, count):
    if count == 0 or avg is None:
        return "🆕 Новачок"
    return f"⭐️ {avg:.1f} ({count})"

def get_user_rating(user_id, role="driver"):
    conn = get_connection()
    # Реалізуємо простий варіант: беремо з таблиці users
    # (Для точного підрахунку треба брати з таблиці ratings, але для швидкості можна так)
    col = "rating_driver" if role == "driver" else "rating_pass"
    user = conn.execute(f"SELECT {col} FROM users WHERE user_id = ?", (user_id,)).fetchone()
    
    # Кількість оцінок
    cnt = conn.execute("SELECT COUNT(*) FROM ratings WHERE to_user_id = ? AND role = ?", (user_id, role)).fetchone()[0]
    
    conn.close()
    val = user[col] if user else 5.0
    return (val, cnt)

def add_rating(from_id, to_id, trip_id, role, score):
    conn = get_connection()
    conn.execute("INSERT INTO ratings (from_user_id, to_user_id, trip_id, role, score) VALUES (?, ?, ?, ?, ?)", (from_id, to_id, trip_id, role, score))
    
    # Оновлюємо середнє в users
    avg = conn.execute("SELECT AVG(score) FROM ratings WHERE to_user_id = ? AND role = ?", (to_id, role)).fetchone()[0]
    col = "rating_driver" if role == "driver" else "rating_pass"
    conn.execute(f"UPDATE users SET {col} = ? WHERE user_id = ?", (avg, to_id))
    
    conn.commit()
    conn.close()

def save_search_history(user_id, origin, destination):
    conn = get_connection()
    # Видаляємо такий самий запис, щоб оновити час
    conn.execute("DELETE FROM search_history WHERE user_id = ? AND origin = ? AND destination = ?", (user_id, origin, destination))
    conn.execute("INSERT INTO search_history (user_id, origin, destination) VALUES (?, ?, ?)", (user_id, origin, destination))
    # Лишаємо останні 5
    conn.execute("DELETE FROM search_history WHERE rowid NOT IN (SELECT rowid FROM search_history WHERE user_id = ? ORDER BY rowid DESC LIMIT 5) AND user_id = ?", (user_id, user_id))
    conn.commit()
    conn.close()

def get_recent_searches(user_id):
    conn = get_connection()
    rows = conn.execute("SELECT origin, destination FROM search_history WHERE user_id = ? ORDER BY timestamp DESC LIMIT 5", (user_id,)).fetchall()
    conn.close()
    return [(r['origin'], r['destination']) for r in rows]

def add_or_update_city(city_name):
    conn = get_connection()
    conn.execute('''
        INSERT INTO cities (name, search_count) VALUES (?, 1)
        ON CONFLICT(name) DO UPDATE SET search_count = search_count + 1
    ''', (city_name,))
    conn.commit()
    conn.close()

def get_city_suggestion(text):
    # Тут можна реалізувати пошук по базі
    return None

def add_subscription(user_id, origin, dest, date):
    conn = get_connection()
    conn.execute("INSERT INTO subscriptions VALUES (?, ?, ?, ?)", (user_id, origin, dest, date))
    conn.commit()
    conn.close()

def log_event(user_id, event, details):
    print(f"📊 LOG: {user_id} | {event} | {details}")
    if event in ["search_success", "search_empty"]:
        update_user_activity(user_id, None, None)

def perform_db_cleanup():
    conn = get_connection()
    conn.execute("DELETE FROM chat_history WHERE timestamp < datetime('now', '-7 days')")
    conn.execute("DELETE FROM trips WHERE status IN ('finished', 'cancelled') AND date < date('now', '-60 days')")
    conn.execute("DELETE FROM search_history WHERE timestamp < datetime('now', '-2 days')")
    conn.commit()
    conn.close()
# ==========================================
# 🕒 ФОНОВІ ЗАДАЧІ (АРХІВАЦІЯ)
# ==========================================

def archive_old_trips_db():
    """Повертає всі активні поїздки для перевірки часу в main.py."""
    conn = get_connection()
    # Беремо всі активні, щоб main.py перевірив їх час
    rows = conn.execute("SELECT id, user_id, date, time FROM trips WHERE status='active'").fetchall()
    conn.close()
    return [dict(row) for row in rows]

def mark_trip_finished(trip_id):
    """Позначає поїздку як завершену (Status: finished)."""
    conn = get_connection()
    conn.execute("UPDATE trips SET status='finished' WHERE id=?", (trip_id,))
    conn.commit()
    conn.close()
# ==========================================
# 🏙 МІСТА (ДЛЯ UTILS.PY)
# ==========================================

def get_all_cities_names():
    """Повертає список всіх міст для автодоповнення."""
    conn = get_connection()
    rows = conn.execute("SELECT name FROM cities ORDER BY search_count DESC").fetchall()
    conn.close()
    return [row['name'] for row in rows]
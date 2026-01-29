import sqlite3
import asyncio
from datetime import datetime
from config import DB_FILE

def get_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    # 🔥 Вмикаємо WAL режим для швидкості та конкурентності
    conn.execute("PRAGMA journal_mode=WAL;") 
    conn.execute("PRAGMA synchronous=NORMAL;")
    
    cursor = conn.cursor()
    
    # 1. Користувачі
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            name TEXT,
            phone TEXT,
            model TEXT DEFAULT '-',
            number TEXT DEFAULT '-',
            color TEXT DEFAULT '-',
            rating_driver REAL DEFAULT 5.0,
            rating_pass REAL DEFAULT 5.0,
            trips_count INTEGER DEFAULT 0,
            is_banned INTEGER DEFAULT 0,
            terms_accepted INTEGER DEFAULT 0,
            ref_source TEXT,
            is_blocked_bot INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_active DATETIME DEFAULT CURRENT_TIMESTAMP
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
            description TEXT DEFAULT '' 
        )
    ''')

    # 3. Бронювання
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trip_id TEXT,
            passenger_id INTEGER,
            status TEXT DEFAULT 'confirmed',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 4. Історія повідомлень
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER,
            receiver_id INTEGER,
            message TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            is_read INTEGER DEFAULT 0
        )
    ''')

    # 5. Активні сесії чатів
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS active_chats (
            user_id INTEGER PRIMARY KEY,
            partner_id INTEGER
        )
    ''')

    # 6. Очистка інтерфейсу
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS interface_cleanup (
            user_id INTEGER,
            message_id INTEGER
        )
    ''')

    # 7. Інші таблиці
    cursor.execute('CREATE TABLE IF NOT EXISTS cities (name TEXT PRIMARY KEY, search_count INTEGER DEFAULT 1)')
    cursor.execute('CREATE TABLE IF NOT EXISTS search_history (user_id INTEGER, origin TEXT, destination TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)')
    cursor.execute('CREATE TABLE IF NOT EXISTS subscriptions (user_id INTEGER, origin TEXT, destination TEXT, date TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS ratings (id INTEGER PRIMARY KEY AUTOINCREMENT, from_user_id INTEGER, to_user_id INTEGER, trip_id TEXT, role TEXT, score INTEGER, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)')

    conn.commit()
    conn.close()

# ==========================================
# 📊 АНАЛІТИКА (РОЗШИРЕНА)
# ==========================================

def get_stats_general():
    conn = get_connection()
    active = conn.execute("SELECT COUNT(*) FROM trips WHERE status='active'").fetchone()[0]
    finished = conn.execute("SELECT COUNT(*) FROM trips WHERE status='finished'").fetchone()[0]
    bookings = conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]
    conn.close()
    return {'active_trips': active, 'finished_trips': finished, 'total_bookings': bookings}

def get_stats_extended():
    conn = get_connection()
    total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    blocked = conn.execute("SELECT COUNT(*) FROM users WHERE is_blocked_bot=1").fetchone()[0]
    new_today = conn.execute("SELECT COUNT(*) FROM users WHERE date(created_at) = date('now')").fetchone()[0]
    
    # Розподіл ролей
    drivers = conn.execute("SELECT COUNT(*) FROM users WHERE model != '-'").fetchone()[0]
    passengers = total - drivers

    dau = conn.execute('''
        SELECT COUNT(DISTINCT user_id) FROM (
            SELECT user_id FROM search_history WHERE timestamp > datetime('now', '-1 day')
            UNION
            SELECT passenger_id as user_id FROM bookings WHERE created_at > datetime('now', '-1 day')
        )
    ''').fetchone()[0]
    
    mau = conn.execute('''
        SELECT COUNT(DISTINCT user_id) FROM (
            SELECT user_id FROM search_history WHERE timestamp > datetime('now', '-30 days')
            UNION
            SELECT passenger_id as user_id FROM bookings WHERE created_at > datetime('now', '-30 days')
        )
    ''').fetchone()[0]
    if mau == 0: mau = 1 

    conn.close()
    return {
        'total_users': total, 'blocked': blocked, 'new_today': new_today, 
        'dau': dau, 'mau': mau, 
        'drivers': drivers, 'passengers': passengers
    }

def get_financial_stats():
    conn = get_connection()
    gmv = conn.execute("SELECT SUM(price * seats_taken) FROM trips WHERE status='finished'").fetchone()[0]
    conn.close()
    return gmv if gmv else 0

def get_efficiency_stats():
    """Середній чек та заповнюваність."""
    conn = get_connection()
    
    # Середня ціна активних поїздок
    avg_price = conn.execute("SELECT AVG(price) FROM trips WHERE status='active'").fetchone()[0]
    
    # Заповнюваність (Зайнято / Всього місць)
    occupancy_data = conn.execute("SELECT SUM(seats_taken), SUM(seats_total) FROM trips WHERE status IN ('active', 'finished')").fetchone()
    
    conn.close()
    
    taken = occupancy_data[0] if occupancy_data and occupancy_data[0] else 0
    total = occupancy_data[1] if occupancy_data and occupancy_data[1] else 1
    
    occupancy_rate = round((taken / total) * 100, 1) if total > 0 else 0
    avg_price = round(avg_price, 0) if avg_price else 0
    
    return {'avg_price': avg_price, 'occupancy': occupancy_rate}

def get_top_sources():
    conn = get_connection()
    rows = conn.execute("SELECT ref_source, COUNT(*) as cnt FROM users WHERE ref_source IS NOT NULL GROUP BY ref_source ORDER BY cnt DESC LIMIT 5").fetchall()
    conn.close()
    return [(r['ref_source'], r['cnt']) for r in rows]

def get_conversion_rate():
    conn = get_connection()
    searches = conn.execute("SELECT COUNT(*) FROM search_history").fetchone()[0]
    bookings = conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]
    conn.close()
    if searches == 0: return 0
    return round((bookings / searches) * 100, 1)

def get_peak_hours():
    conn = get_connection()
    rows = conn.execute("SELECT substr(time, 1, 2) as hour, COUNT(*) as cnt FROM trips GROUP BY hour ORDER BY cnt DESC LIMIT 3").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_top_failed_searches():
    conn = get_connection()
    rows = conn.execute("SELECT origin || ' - ' || destination as event_data, COUNT(*) as cnt FROM search_history GROUP BY origin, destination ORDER BY cnt DESC LIMIT 3").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_top_routes(limit=3):
    conn = get_connection()
    rows = conn.execute("SELECT origin, destination, COUNT(*) as cnt FROM trips GROUP BY origin, destination ORDER BY cnt DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ==========================================
# 👤 КОРИСТУВАЧІ
# ==========================================

# У файлі database.py

def get_user(user_id):
    conn = get_connection()
    user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(user) if user else None

def save_user(user_id, name, username, phone=None, model='-', body='-', color='-', number='-', ref_source=None):
    conn = get_connection()
    if get_user(user_id):
        # Оновлення існуючого користувача
        updates = []
        params = []
        if name: updates.append("name=?"); params.append(name)
        if username: updates.append("username=?"); params.append(username)
        if phone: updates.append("phone=?"); params.append(phone)
        if model != '-': updates.append("model=?"); params.append(model)
        if number != '-': updates.append("number=?"); params.append(number)
        if color != '-': updates.append("color=?"); params.append(color)
        
        # Оновлюємо реферала тільки якщо він ще не встановлений
        if ref_source:
            updates.append("ref_source = COALESCE(ref_source, ?)")
            params.append(ref_source)
            
        updates.append("last_active=CURRENT_TIMESTAMP")
        
        sql = f"UPDATE users SET {', '.join(updates)} WHERE user_id=?"
        params.append(user_id)
        conn.execute(sql, params)
    else:
        # Створення нового користувача
        conn.execute('''
            INSERT INTO users (user_id, username, name, phone, ref_source, created_at, last_active) 
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ''', (user_id, username, name, phone if phone else '-', ref_source))
    conn.commit()
    conn.close()

def update_user_activity(user_id, username, name):
    conn = get_connection()
    conn.execute('''
        INSERT INTO users (user_id, username, name, phone, created_at, last_active) 
        VALUES (?, ?, ?, '-', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
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
    val = 1 if is_blocked else 0
    conn.execute("UPDATE users SET is_blocked_bot = ? WHERE user_id = ?", (val, user_id))
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
# 💬 ЧАТ
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

def get_chat_history_text(user1, user2):
    conn = get_connection()
    rows = conn.execute('''
        SELECT sender_id, message, timestamp FROM chat_history 
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

# ==========================================
# 🏙 МІСТА
# ==========================================

def add_or_update_city(city_name):
    conn = get_connection()
    conn.execute('''
        INSERT INTO cities (name, search_count) VALUES (?, 1)
        ON CONFLICT(name) DO UPDATE SET search_count = search_count + 1
    ''', (city_name,))
    conn.commit()
    conn.close()

def get_all_cities_names():
    conn = get_connection()
    rows = conn.execute("SELECT name FROM cities ORDER BY search_count DESC").fetchall()
    conn.close()
    return [row['name'] for row in rows]

def log_event(user_id, event, details):
    print(f"📊 LOG: {user_id} | {event} | {details}")
    if event == "search_success" or event == "search_empty":
        update_user_activity(user_id, None, None)

# ==========================================
# 🚗 ПОЇЗДКИ (ДІЇ)
# ==========================================

def create_trip(trip_id, user_id, origin, destination, date, time, seats, price, description=""):
    conn = get_connection()
    conn.execute("INSERT INTO trips (id, user_id, origin, destination, date, time, seats_total, price, description) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (trip_id, user_id, origin, destination, date, time, seats, price, description))
    conn.commit()
    conn.close()

def get_driver_active_trips(user_id):
    conn = get_connection()
    rows = conn.execute("SELECT * FROM trips WHERE user_id = ? AND status = 'active' ORDER BY date, time", (user_id,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_last_driver_trip(user_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM trips WHERE user_id = ? ORDER BY rowid DESC LIMIT 1", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def get_driver_history(user_id):
    conn = get_connection()
    rows = conn.execute("SELECT origin, destination, date, time, price, seats_total, seats_taken, status FROM trips WHERE user_id = ? AND status IN ('finished', 'cancelled') ORDER BY rowid DESC LIMIT 10", (user_id,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]

def finish_trip(trip_id):
    conn = get_connection()
    conn.execute("UPDATE trips SET status = 'finished' WHERE id = ?", (trip_id,))
    conn.commit()
    conn.close()

def cancel_trip_full(trip_id, driver_id):
    conn = get_connection()
    # Якщо викликає адмін (driver_id=0 або не збігається), то просто ігноруємо перевірку власника
    # Але для повідомлень нам все одно треба дізнатись, хто справжній водій
    trip = conn.execute("SELECT origin, destination, user_id FROM trips WHERE id = ?", (trip_id,)).fetchone()
    
    passengers = conn.execute("SELECT passenger_id FROM bookings WHERE trip_id = ?", (trip_id,)).fetchall()
    conn.execute("UPDATE trips SET status = 'cancelled' WHERE id = ?", (trip_id,))
    conn.execute("DELETE FROM bookings WHERE trip_id = ?", (trip_id,))
    conn.commit()
    conn.close()
    
    # Повертаємо ID пасажирів для розсилки
    passenger_ids = [p['passenger_id'] for p in passengers]
    return dict(trip), passenger_ids

# ==========================================
# 🔍 ПОШУК ТА ПАГІНАЦІЯ
# ==========================================

def search_trips(origin, destination, date, viewer_id):
    # Залишаємо для сумісності, але краще юзати search_trips_page
    conn = get_connection()
    rows = conn.execute('''
        SELECT t.*, u.name as driver_name, u.rating_driver, u.model, u.color, u.user_id
        FROM trips t
        JOIN users u ON t.user_id = u.user_id
        WHERE t.origin = ? AND t.destination = ? AND t.date = ? AND t.status = 'active'
          AND t.seats_taken < t.seats_total AND t.user_id != ?
    ''', (origin, destination, date, viewer_id)).fetchall()
    conn.close()
    return rows

def search_trips_page(origin, destination, date, viewer_id, limit, offset):
    """Шукає поїздки з пагінацією (LIMIT/OFFSET)."""
    conn = get_connection()
    
    rows = conn.execute('''
        SELECT t.*, u.name as driver_name, u.rating_driver, u.model, u.color, u.user_id
        FROM trips t
        JOIN users u ON t.user_id = u.user_id
        WHERE t.origin = ? AND t.destination = ? AND t.date = ? AND t.status = 'active'
          AND t.seats_taken < t.seats_total AND t.user_id != ?
        ORDER BY t.time ASC
        LIMIT ? OFFSET ?
    ''', (origin, destination, date, viewer_id, limit, offset)).fetchall()
    
    count = conn.execute('''
        SELECT COUNT(*)
        FROM trips t
        WHERE t.origin = ? AND t.destination = ? AND t.date = ? AND t.status = 'active'
          AND t.seats_taken < t.seats_total AND t.user_id != ?
    ''', (origin, destination, date, viewer_id)).fetchone()[0]
    
    conn.close()
    return [dict(row) for row in rows], count

def get_trip_details(trip_id):
    conn = get_connection()
    row = conn.execute('''
        SELECT t.*, u.name, u.phone, u.rating_driver, u.model, u.color
        FROM trips t JOIN users u ON t.user_id = u.user_id WHERE t.id = ?
    ''', (trip_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def get_all_active_trips_paginated(limit, offset):
    """🔥 Для Адмінки: Отримує активні поїздки з повною інфою."""
    conn = get_connection()
    
    rows = conn.execute('''
        SELECT t.*, u.name, u.phone, u.username, u.model, u.color, u.rating_driver
        FROM trips t 
        JOIN users u ON t.user_id = u.user_id 
        WHERE t.status = 'active' 
        ORDER BY t.rowid DESC 
        LIMIT ? OFFSET ?
    ''', (limit, offset)).fetchall()
    
    count = conn.execute("SELECT COUNT(*) FROM trips WHERE status='active'").fetchone()[0]
    conn.close()
    
    return [dict(row) for row in rows], count

# ==========================================
# 🎫 БРОНЮВАННЯ & ІСТОРІЯ ПАСАЖИРА
# ==========================================

def add_booking(trip_id, passenger_id):
    conn = get_connection()
    cursor = conn.cursor()
    exist = cursor.execute("SELECT id FROM bookings WHERE trip_id = ? AND passenger_id = ?", (trip_id, passenger_id)).fetchone()
    if exist: conn.close(); return False, "Вже заброньовано."
    trip = cursor.execute("SELECT seats_taken, seats_total, user_id FROM trips WHERE id = ?", (trip_id,)).fetchone()
    if not trip or trip['seats_taken'] >= trip['seats_total']: conn.close(); return False, "Місць немає."
    if trip['user_id'] == passenger_id: conn.close(); return False, "Не можна у себе."
    cursor.execute("INSERT INTO bookings (trip_id, passenger_id) VALUES (?, ?)", (trip_id, passenger_id))
    cursor.execute("UPDATE trips SET seats_taken = seats_taken + 1 WHERE id = ?", (trip_id,))
    conn.commit(); conn.close()
    return True, "Success"

def get_user_bookings(user_id):
    conn = get_connection()
    rows = conn.execute('''
        SELECT b.id, b.trip_id, t.origin, t.destination, t.date, t.time, 
               u.name as driver_name, u.phone as driver_phone, t.user_id as driver_id
        FROM bookings b
        JOIN trips t ON b.trip_id = t.id
        JOIN users u ON t.user_id = u.user_id
        WHERE b.passenger_id = ? AND t.status = 'active'
        ORDER BY t.date ASC, t.time ASC
    ''', (user_id,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_passenger_history(user_id):
    conn = get_connection()
    rows = conn.execute('''
        SELECT t.origin, t.destination, t.date, t.time, t.price,
               u.name as driver_name, u.phone as driver_phone
        FROM bookings b
        JOIN trips t ON b.trip_id = t.id
        JOIN users u ON t.user_id = u.user_id
        WHERE b.passenger_id = ? AND t.status = 'finished'
        ORDER BY t.rowid DESC LIMIT 10
    ''', (user_id,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_trip_passengers(trip_id):
    conn = get_connection()
    rows = conn.execute("SELECT u.user_id, u.name, u.phone, b.id as booking_id FROM bookings b JOIN users u ON b.passenger_id = u.user_id WHERE b.trip_id = ?", (trip_id,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]

def delete_booking(booking_id, passenger_id):
    conn = get_connection()
    cursor = conn.cursor()
    booking = cursor.execute("SELECT trip_id FROM bookings WHERE id = ? AND passenger_id = ?", (booking_id, passenger_id)).fetchone()
    if not booking: conn.close(); return None
    trip_id = booking['trip_id']
    trip = cursor.execute("SELECT t.user_id as driver_id, u.name as passenger_name FROM trips t, users u WHERE t.id = ? AND u.user_id = ?", (trip_id, passenger_id)).fetchone()
    cursor.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
    cursor.execute("UPDATE trips SET seats_taken = seats_taken - 1 WHERE id = ?", (trip_id,))
    conn.commit(); conn.close()
    return dict(trip)

def kick_passenger(booking_id, driver_id):
    conn = get_connection()
    cursor = conn.cursor()
    booking = cursor.execute("SELECT b.trip_id, b.passenger_id FROM bookings b JOIN trips t ON b.trip_id = t.id WHERE b.id = ? AND t.user_id = ?", (booking_id, driver_id)).fetchone()
    if not booking: conn.close(); return None
    cursor.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
    cursor.execute("UPDATE trips SET seats_taken = seats_taken - 1 WHERE id = ?", (booking['trip_id'],))
    conn.commit(); conn.close()
    return dict(booking)

def save_search_history(user_id, origin, destination):
    conn = get_connection()
    conn.execute("DELETE FROM search_history WHERE user_id = ? AND origin = ? AND destination = ?", (user_id, origin, destination))
    conn.execute("INSERT INTO search_history (user_id, origin, destination) VALUES (?, ?, ?)", (user_id, origin, destination))
    conn.execute("DELETE FROM search_history WHERE rowid NOT IN (SELECT rowid FROM search_history WHERE user_id = ? ORDER BY rowid DESC LIMIT 5) AND user_id = ?", (user_id, user_id))
    conn.commit()
    conn.close()

def get_recent_searches(user_id):
    conn = get_connection()
    rows = conn.execute('''
        SELECT origin, destination 
        FROM search_history 
        WHERE user_id = ? 
        GROUP BY origin, destination 
        ORDER BY MAX(timestamp) DESC 
        LIMIT 5
    ''', (user_id,)).fetchall()
    conn.close()
    return [(row['origin'], row['destination']) for row in rows]

# ==========================================
# ⭐ РЕЙТИНГ & ПІДПИСКИ
# ==========================================

def add_rating(from_id, to_id, trip_id, role, score):
    conn = get_connection()
    conn.execute("INSERT INTO ratings (from_user_id, to_user_id, trip_id, role, score) VALUES (?, ?, ?, ?, ?)", (from_id, to_id, trip_id, role, score))
    col = "rating_driver" if role == "driver" else "rating_pass"
    avg = conn.execute(f"SELECT AVG(score) FROM ratings WHERE to_user_id = ? AND role = ?", (to_id, role)).fetchone()[0]
    conn.execute(f"UPDATE users SET {col} = ? WHERE user_id = ?", (avg, to_id))
    conn.commit(); conn.close()

def get_user_rating(user_id, role="driver"):
    conn = get_connection()
    row = conn.execute("SELECT AVG(score) as avg, COUNT(*) as cnt FROM ratings WHERE to_user_id = ? AND role = ?", (user_id, role)).fetchone()
    conn.close()
    return (row['avg'] if row['avg'] else 5.0, row['cnt'])

def format_rating(avg, count):
    if count == 0 or avg is None:
        return "🆕 Новачок"
    return f"⭐️ {avg:.1f} ({count})"

def add_subscription(user_id, origin, dest, date):
    conn = get_connection()
    conn.execute("INSERT INTO subscriptions VALUES (?, ?, ?, ?)", (user_id, origin, dest, date))
    conn.commit(); conn.close()

def get_subscribers_for_trip(origin, dest, date):
    conn = get_connection()
    rows = conn.execute("SELECT user_id FROM subscriptions WHERE origin = ? AND destination = ? AND date = ?", (origin, dest, date)).fetchall()
    conn.execute("DELETE FROM subscriptions WHERE origin = ? AND destination = ? AND date = ?", (origin, dest, date))
    conn.commit(); conn.close()
    return [row['user_id'] for row in rows]

# ==========================================
# 🧹 ФОНОВІ ЗАДАЧІ (DB CLEANUP)
# ==========================================

def archive_old_trips_db():
    conn = get_connection()
    rows = conn.execute("SELECT id, user_id, date, time FROM trips WHERE status='active'").fetchall()
    conn.close()
    return [dict(row) for row in rows]

def mark_trip_finished(trip_id):
    conn = get_connection()
    conn.execute("UPDATE trips SET status='finished' WHERE id=?", (trip_id,))
    conn.commit()
    conn.close()

def perform_db_cleanup():
    conn = get_connection()
    conn.execute("DELETE FROM chat_history WHERE timestamp < datetime('now', '-7 days')")
    conn.execute("DELETE FROM trips WHERE status IN ('finished', 'cancelled') AND date < date('now', '-60 days')")
    conn.execute("DELETE FROM search_history WHERE timestamp < datetime('now', '-2 days')")
    conn.execute("DELETE FROM bookings WHERE trip_id NOT IN (SELECT id FROM trips)")
    conn.commit()
    conn.close()
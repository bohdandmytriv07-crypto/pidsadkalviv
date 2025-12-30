import sqlite3
from datetime import datetime
from typing import Optional, List, Tuple, Any, Dict
from config import DB_FILE

# ==========================================
# 🔌 ПІДКЛЮЧЕННЯ ДО БД
# ==========================================

def get_db() -> sqlite3.Connection:
    """
    Створює з'єднання з БД та повертає об'єкт connection.
    Використовує sqlite3.Row для доступу до колонок за назвою.
    """
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """
    Ініціалізація таблиць при першому запуску.
    """
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        
        # 1. Таблиця користувачів
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            phone TEXT,
            model TEXT DEFAULT '-',
            body TEXT DEFAULT '-',
            color TEXT DEFAULT '-',
            number TEXT DEFAULT '-',
            rating REAL DEFAULT 5.0,
            is_banned INTEGER DEFAULT 0
        )""")

        # 2. Таблиця поїздок
        cursor.execute("""
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
        )""")

        # 3. Таблиця бронювань
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trip_id TEXT,
            passenger_id INTEGER,
            seats_count INTEGER DEFAULT 1,
            status TEXT DEFAULT 'confirmed',
            FOREIGN KEY(trip_id) REFERENCES trips(id),
            FOREIGN KEY(passenger_id) REFERENCES users(user_id),
            UNIQUE(trip_id, passenger_id)
        )""")
        
        # 4. Історія пошуку
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS search_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            origin TEXT,
            destination TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )""")
        
        # 5. Підписки на сповіщення
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            origin TEXT,
            destination TEXT,
            date TEXT
        )""")
        
        # 6. Активні чати
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS active_chats (
            user_id INTEGER PRIMARY KEY,
            partner_id INTEGER
        )""")
        
        # 7. Логи повідомлень чату (для очищення)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            message_id INTEGER
        )""")
        
        conn.commit()
        
# ==========================================
# 👤 КОРИСТУВАЧІ (USERS)
# ==========================================

def save_user(uid: int, name: str, phone: str, model: str = None, 
              body: str = None, color: str = None, number: str = None):
    """Зберігає або оновлює дані користувача."""
    with get_db() as conn:
        cursor = conn.cursor()
        user = cursor.execute("SELECT * FROM users WHERE user_id = ?", (uid,)).fetchone()
        
        if user:
            new_model = model if model else user['model']
            new_body = body if body else user['body']
            new_color = color if color else user['color']
            new_number = number if number else user['number']
            
            cursor.execute("""
                UPDATE users SET name=?, phone=?, model=?, body=?, color=?, number=?
                WHERE user_id=?
            """, (name, phone, new_model, new_body, new_color, new_number, uid))
        else:
            cursor.execute("""
                INSERT INTO users (user_id, name, phone, model, body, color, number)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (uid, name, phone, model or '-', body or '-', color or '-', number or '-'))
        conn.commit()


def get_user(user_id: int) -> Optional[sqlite3.Row]:
    """Повертає дані користувача або None."""
    with get_db() as conn:
        return conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()


def set_ban_status(user_id: int, is_banned: int):
    """Встановлює статус бану: 1 - забанити, 0 - розбанити."""
    with get_db() as conn:
        conn.execute("UPDATE users SET is_banned = ? WHERE user_id = ?", (is_banned, user_id))
        conn.commit()


def is_user_banned(user_id: int) -> bool:
    """Перевіряє, чи забанений користувач."""
    with get_db() as conn:
        row = conn.execute("SELECT is_banned FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return bool(row and row['is_banned'] == 1)


# ==========================================
# 🚗 ПОЇЗДКИ (TRIPS)
# ==========================================

def create_trip(trip_id: str, user_id: int, origin: str, dest: str, 
                date: str, time: str, seats: int, price: int):
    """Створення нової поїздки."""
    with get_db() as conn:
        conn.execute("""
            INSERT INTO trips (id, user_id, origin, destination, date, time, seats_total, price)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (trip_id, user_id, origin, dest, date, time, seats, price))
        conn.commit()


def search_trips(origin: str, dest: str, date: str, exclude_user_id: int) -> List[sqlite3.Row]:
    """Пошук активних поїздок за маршрутом і датою."""
    results = []
    now = datetime.now()
    current_date_str = now.strftime("%d.%m")
    current_time = now.time()

    with get_db() as conn:
        rows = conn.execute("""
            SELECT t.*, u.name as driver_name, u.model, u.color, u.rating 
            FROM trips t
            JOIN users u ON t.user_id = u.user_id
            WHERE t.date = ? 
              AND t.status = 'active' 
              AND t.seats_taken < t.seats_total
              AND t.user_id != ? 
            ORDER BY t.time ASC, t.price ASC
        """, (date, exclude_user_id)).fetchall()
        
        search_origin = origin.lower().strip()
        search_dest = dest.lower().strip()
        
        for row in rows:
            if search_origin not in row['origin'].lower() or search_dest not in row['destination'].lower():
                continue
                
            if row['date'] == current_date_str:
                try:
                    trip_time = datetime.strptime(row['time'], "%H:%M").time()
                    if trip_time < current_time:
                        continue 
                except ValueError:
                    pass 
            
            results.append(row)
                
    return results


def get_trip_details(trip_id: str) -> Optional[sqlite3.Row]:
    """Отримати повну інформацію про поїздку за ID."""
    with get_db() as conn:
        return conn.execute("""
            SELECT t.*, u.name, u.phone, u.model, u.color, u.number 
            FROM trips t
            JOIN users u ON t.user_id = u.user_id
            WHERE t.id = ?
        """, (trip_id,)).fetchone()


def get_driver_active_trips(driver_id: int) -> List[sqlite3.Row]:
    """Повертає всі активні поїздки конкретного водія."""
    with get_db() as conn:
        return conn.execute("""
            SELECT * FROM trips 
            WHERE user_id = ? AND status = 'active'
            ORDER BY date, time
        """, (driver_id,)).fetchall()


def get_all_active_trips() -> List[sqlite3.Row]:
    """Повертає ВСІ поїздки зі статусом 'active' (для фонових задач)."""
    with get_db() as conn:
        return conn.execute("SELECT id, date, time, destination, user_id, is_notified FROM trips WHERE status = 'active'").fetchall()


def get_last_driver_trip(driver_id: int) -> Optional[sqlite3.Row]:
    """Повертає останню створену водієм поїздку (для функції повтору)."""
    with get_db() as conn:
        return conn.execute("""
            SELECT * FROM trips 
            WHERE user_id = ? 
            ORDER BY rowid DESC LIMIT 1
        """, (driver_id,)).fetchone()


def finish_trip(trip_id: str):
    """Змінює статус поїздки на 'finished'."""
    with get_db() as conn:
        conn.execute("UPDATE trips SET status = 'finished' WHERE id = ?", (trip_id,))
        conn.commit()


def cancel_trip_full(trip_id: str, driver_id: int) -> Tuple[Optional[sqlite3.Row], List[int]]:
    """Скасовує поїздку водієм (М'ЯКЕ ВИДАЛЕННЯ)."""
    with get_db() as conn:
        cursor = conn.cursor()
        
        trip = cursor.execute(
            "SELECT id, origin, destination, date, time FROM trips WHERE id = ? AND user_id = ?", 
            (trip_id, driver_id)
        ).fetchone()
        
        if not trip:
            return None, []

        passengers = cursor.execute(
            "SELECT passenger_id FROM bookings WHERE trip_id = ?", (trip_id,)
        ).fetchall()
        passenger_ids = [p['passenger_id'] for p in passengers]

        cursor.execute("UPDATE trips SET status = 'canceled' WHERE id = ?", (trip_id,))
        
        conn.commit()
        return trip, passenger_ids


def mark_trip_notified(trip_id: str):
    """Ставить відмітку, що нагадування по цій поїздці вже надіслано."""
    with get_db() as conn:
        conn.execute("UPDATE trips SET is_notified = 1 WHERE id = ?", (trip_id,))
        conn.commit()


# ==========================================
# 🎫 БРОНЮВАННЯ (BOOKINGS)
# ==========================================

def add_booking(trip_id: str, passenger_id: int) -> Tuple[bool, str]:
    """Створює бронювання. Повертає (Success: bool, Message: str)."""
    with get_db() as conn:
        cursor = conn.cursor()
        
        trip = cursor.execute("SELECT user_id, seats_total, seats_taken FROM trips WHERE id = ?", (trip_id,)).fetchone()
        if not trip:
            return False, "Поїздку не знайдено."

        if trip['user_id'] == passenger_id:
            return False, "❌ Ви не можете бронювати власну поїздку!"
        
        if trip['seats_taken'] >= trip['seats_total']:
            return False, "На жаль, місць більше немає."
            
        check = cursor.execute(
            "SELECT id FROM bookings WHERE trip_id = ? AND passenger_id = ?", 
            (trip_id, passenger_id)
        ).fetchone()
        
        if check:
            return False, "Ви вже забронювали місце на цю поїздку."

        try:
            cursor.execute(
                "INSERT INTO bookings (trip_id, passenger_id) VALUES (?, ?)", 
                (trip_id, passenger_id)
            )
            cursor.execute(
                "UPDATE trips SET seats_taken = seats_taken + 1 WHERE id = ?", 
                (trip_id,)
            )
            conn.commit()
            return True, "Місце успішно забронювано!"
        except Exception as e:
            return False, f"Помилка бази даних: {e}"


def delete_booking(booking_id: int, user_id: int) -> Optional[Dict[str, Any]]:
    """Скасовує бронювання пасажиром."""
    with get_db() as conn:
        cursor = conn.cursor()
        
        sql_info = """
            SELECT 
                b.trip_id, 
                t.user_id as driver_id, 
                t.origin, 
                t.destination, 
                t.date, 
                t.time,
                u.name as passenger_name
            FROM bookings b
            JOIN trips t ON b.trip_id = t.id
            JOIN users u ON b.passenger_id = u.user_id
            WHERE b.id = ? AND b.passenger_id = ?
        """
        row = cursor.execute(sql_info, (booking_id, user_id)).fetchone()
        
        if not row:
            return None 

        info = dict(row)

        cursor.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
        cursor.execute("UPDATE trips SET seats_taken = seats_taken - 1 WHERE id = ?", (info['trip_id'],))
        
        conn.commit()
        return info


def get_user_bookings(user_id: int) -> List[sqlite3.Row]:
    """Повертає активні бронювання пасажира."""
    with get_db() as conn:
        return conn.execute("""
            SELECT b.*, t.origin, t.destination, t.date, t.time, t.price, 
                   u.name as driver_name, u.phone as driver_phone, t.user_id as driver_id
            FROM bookings b
            JOIN trips t ON b.trip_id = t.id
            JOIN users u ON t.user_id = u.user_id
            WHERE b.passenger_id = ? AND t.status = 'active'
        """, (user_id,)).fetchall()


def get_user_history(user_id: int) -> List[sqlite3.Row]:
    """Повертає історію завершених поїздок."""
    with get_db() as conn:
        return conn.execute("""
            SELECT t.origin, t.destination, t.date, t.time, t.price, u.name as driver_name
            FROM bookings b
            JOIN trips t ON b.trip_id = t.id
            JOIN users u ON t.user_id = u.user_id
            WHERE b.passenger_id = ? AND t.status = 'finished'
            ORDER BY t.date DESC, t.time DESC
        """, (user_id,)).fetchall()


def get_trip_passengers(trip_id: str) -> List[sqlite3.Row]:
    """Повертає список пасажирів певної поїздки."""
    with get_db() as conn:
        return conn.execute("""
            SELECT b.id as booking_id, u.name, u.phone, u.user_id 
            FROM bookings b
            JOIN users u ON b.passenger_id = u.user_id
            WHERE b.trip_id = ?
        """, (trip_id,)).fetchall()


def kick_passenger(booking_id: int, driver_id: int) -> Optional[Dict[str, Any]]:
    """Водій примусово видаляє пасажира."""
    with get_db() as conn:
        cursor = conn.cursor()
        
        query = """
            SELECT b.trip_id, b.passenger_id, b.seats_count,
                   t.user_id as driver_id, t.origin, t.destination, t.date, t.time,
                   u.name as passenger_name, u.user_id as passenger_id
            FROM bookings b
            JOIN trips t ON b.trip_id = t.id
            JOIN users u ON b.passenger_id = u.user_id
            WHERE b.id = ?
        """
        row = cursor.execute(query, (booking_id,)).fetchone()
        
        if not row or row['driver_id'] != driver_id:
            return None

        cursor.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
        cursor.execute(
            "UPDATE trips SET seats_taken = seats_taken - ? WHERE id = ?", 
            (row['seats_count'], row['trip_id'])
        )
        conn.commit()
        return dict(row)


# ==========================================
# 🔍 ПОШУК ТА ПІДПИСКИ
# ==========================================

def save_search_history(user_id: int, origin: str, dest: str):
    """Зберігає запит пошуку в історію."""
    with get_db() as conn:
        conn.execute("""
            INSERT INTO search_history (user_id, origin, destination)
            VALUES (?, ?, ?)
        """, (user_id, origin, dest))
        conn.commit()


def get_recent_searches(user_id: int, limit: int = 3) -> List[Tuple[str, str]]:
    """Повертає останні унікальні пошукові запити."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT origin, destination 
            FROM search_history
            WHERE user_id = ?
            GROUP BY origin, destination
            ORDER BY MAX(timestamp) DESC
            LIMIT ?
        """, (user_id, limit)).fetchall()
        return [(row['origin'], row['destination']) for row in rows]


def add_subscription(user_id: int, origin: str, dest: str, date: str):
    """Зберігає підписку на сповіщення про маршрут."""
    with get_db() as conn:
        conn.execute("""
            INSERT INTO subscriptions (user_id, origin, destination, date)
            VALUES (?, ?, ?, ?)
        """, (user_id, origin, dest, date))
        conn.commit()


def get_subscribers_for_trip(origin: str, dest: str, date: str) -> List[int]:
    """Знаходить користувачів, які підписані на маршрут."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT user_id FROM subscriptions 
            WHERE lower(origin) = ? AND lower(destination) = ? AND date = ?
        """, (origin.lower(), dest.lower(), date)).fetchall()
        
        return [row['user_id'] for row in rows]


# ==========================================
# 💬 АКТИВНІ ЧАТИ (ЗБЕРЕЖЕННЯ В БД)
# ==========================================

def set_active_chat(user_id: int, partner_id: int):
    """Зберігає інформацію, що user_id спілкується з partner_id."""
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO active_chats (user_id, partner_id) VALUES (?, ?)", 
            (user_id, partner_id)
        )
        conn.commit()

def get_active_chat_partner(user_id: int) -> int | None:
    """Повертає ID співрозмовника або None, якщо чату немає."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT partner_id FROM active_chats WHERE user_id = ?", 
            (user_id,)
        ).fetchone()
        
        return row['partner_id'] if row else None


def delete_active_chat(user_id: int):
    """Видаляє запис про активний чат для користувача."""
    with get_db() as conn:
        conn.execute("DELETE FROM active_chats WHERE user_id = ?", (user_id,))
        conn.commit()

def save_chat_msg(user_id: int, message_id: int):
    """Зберігає ID повідомлення, щоб потім його видалити."""
    with get_db() as conn:
        conn.execute("INSERT INTO chat_logs (user_id, message_id) VALUES (?, ?)", (user_id, message_id))
        conn.commit()

def get_and_clear_chat_msgs(user_id: int) -> List[int]:
    """Повертає список ID повідомлень і очищає їх з бази."""
    with get_db() as conn:
        rows = conn.execute("SELECT message_id FROM chat_logs WHERE user_id = ?", (user_id,)).fetchall()
        ids = [row['message_id'] for row in rows]
        
        conn.execute("DELETE FROM chat_logs WHERE user_id = ?", (user_id,))
        conn.commit()
        return ids
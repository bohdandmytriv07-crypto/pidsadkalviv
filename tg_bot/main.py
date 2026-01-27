import asyncio
import logging
import sys
from datetime import datetime
import pytz
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import ChatMemberUpdatedFilter, KICKED, MEMBER
from aiogram.types import ChatMemberUpdated

# 🔥 Імпорт Middleware
from middlewares import AntiFloodMiddleware, ActivityMiddleware

# 👇 ВИПРАВЛЕНО: Використовуємо API_TOKEN, як у вашому config.py
from config import API_TOKEN 
from database import init_db, get_connection, get_trip_passengers, set_user_blocked_bot

# Імпорти хендлерів
from handlers import common, passenger, driver, admin, profile, chat, rating
from handlers.rating import ask_for_ratings 

# ==========================================
# ⚙️ НАЛАШТУВАННЯ ЛОГУВАННЯ
# ==========================================
def setup_logging():
    """Налаштовує логування в консоль та файл."""
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # 1. Консоль
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    # 2. Файл (макс 5 МБ, зберігає 1 бекап)
    file_handler = RotatingFileHandler("bot.log", maxBytes=5*1024*1024, backupCount=1, encoding="utf-8")
    file_handler.setFormatter(formatter)

    logging.basicConfig(
        level=logging.INFO,
        handlers=[console_handler, file_handler]
    )

logger = logging.getLogger(__name__)

# ==========================================
# 🕒 ФОНОВІ ЗАДАЧІ
# ==========================================
async def background_tasks(bot: Bot):
    logger.info("🕒 Планувальник фонових задач запущено.")
    kyiv_tz = pytz.timezone('Europe/Kyiv')
    
    while True:
        try:
            # Перевіряємо раз на годину (3600 сек), частіше для очистки не треба
            # Але для архівації поїздок краще частіше. Давайте раз на 10 хвилин (600 сек).
            await asyncio.sleep(600) 
            
            conn = get_connection()
            cursor = conn.cursor()
            now = datetime.now(kyiv_tz)
            
            # --- 1. АРХІВАЦІЯ АКТИВНИХ ПОЇЗДОК (Які щойно завершились) ---
            rows = cursor.execute("SELECT id, user_id, date, time FROM trips WHERE status='active'").fetchall()
            archived_count = 0
            
            for row in rows:
                try:
                    trip_dt_str = f"{row['date']}.{now.year}"
                    trip_full_dt = datetime.strptime(f"{trip_dt_str} {row['time']}", "%d.%m.%Y %H:%M")
                    trip_full_dt = kyiv_tz.localize(trip_full_dt)

                    # Якщо час поїздки минув
                    if trip_full_dt < now:
                        trip_id, driver_id = row['id'], row['user_id']
                        cursor.execute("UPDATE trips SET status='finished' WHERE id=?", (trip_id,))
                        
                        passengers = get_trip_passengers(trip_id)
                        if passengers:
                            asyncio.create_task(ask_for_ratings(bot, trip_id, driver_id, passengers))
                        
                        archived_count += 1
                except ValueError: continue 
            
            if archived_count > 0:
                conn.commit() # Важливо комітити відразу
                logger.info(f"🏁 Завершено {archived_count} поїздок.")


            # --- 2. ГЕНЕРАЛЬНЕ ПРИБИРАННЯ (CLEANUP) ---
            
            # 🧹 1. Чати: видаляємо все старше 7 днів
            cursor.execute("DELETE FROM chat_history WHERE timestamp < datetime('now', '-7 days')")
            del_msgs = cursor.rowcount
            
            # 🧹 2. Старі поїздки: видаляємо завершені/скасовані старше 60 днів
            cursor.execute("DELETE FROM trips WHERE status IN ('finished', 'cancelled') AND date < date('now', '-60 days')")
            del_trips = cursor.rowcount
            
            # 🧹 3. Історія пошуку: видаляємо старше 2 днів (вона не має цінності)
            cursor.execute("DELETE FROM search_history WHERE timestamp < datetime('now', '-2 days')")
            
            # 🧹 4. Бронювання-"сироти" (де поїздки вже видалені)
            cursor.execute("DELETE FROM bookings WHERE trip_id NOT IN (SELECT id FROM trips)")
            
            # 🧹 5. Старі підписки (актуальність втрачається після дати поїздки)
            # Тут складніше, бо дата текстом '27.01'. Просто чистимо всі підписки, створені місяць тому (якщо б була колонка created_at).
            # В поточній схемі можна просто очищати таблицю раз на місяць, або додати логіку парсингу дати.
            # Поки лишимо як є, підписки займають мало місця.

            if del_msgs > 0 or del_trips > 0:
                conn.commit()
                logger.info(f"♻️ Очищено сміття: {del_msgs} повідомлень чату, {del_trips} старих поїздок.")
            
            conn.close()

        except Exception as e:
            logger.error(f"⚠️ Background Task Error: {e}")
            await asyncio.sleep(60)

# ==========================================
# 🚫 ОБРОБКА БЛОКУВАНЬ КОРИСТУВАЧАМИ
# ==========================================
async def on_user_block(event: ChatMemberUpdated):
    """Спрацьовує, коли юзер блокує/розблоковує бота."""
    user_id = event.from_user.id
    if event.new_chat_member.status == KICKED:
        logger.info(f"User {user_id} blocked bot.")
        set_user_blocked_bot(user_id, True)
    elif event.new_chat_member.status == MEMBER:
        logger.info(f"User {user_id} unblocked bot.")
        set_user_blocked_bot(user_id, False)

async def global_error_handler(event: types.ErrorEvent):
    logger.exception(f"🔥 Critical Update Error: {event.exception}")
    return True

# ==========================================
# 🚀 MAIN FUNCTION
# ==========================================
async def main():
    setup_logging()
    
    logger.info("🚀 Ініціалізація бази даних...")
    init_db()
    logger.info("✅ База даних готова!")

    # 👇 ВИПРАВЛЕНО: API_TOKEN
    bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    # --- Middleware ---
    dp.message.middleware(ActivityMiddleware())
    dp.callback_query.middleware(ActivityMiddleware())
    dp.message.middleware(AntiFloodMiddleware(limit=0.7))
    dp.callback_query.middleware(AntiFloodMiddleware(limit=0.5))

    # --- Реєстрація подій ---
    dp.my_chat_member.register(on_user_block, ChatMemberUpdatedFilter(member_status_changed=KICKED | MEMBER))
    dp.errors.register(global_error_handler)

    # --- Роутери (Порядок важливий!) ---
    dp.include_router(admin.router)     # Адмінка
    dp.include_router(common.router)    # Старт, меню, підтримка
    dp.include_router(profile.router)   # Профіль
    dp.include_router(driver.router)    # Водій
    dp.include_router(passenger.router) # Пасажир
    dp.include_router(chat.router)      # Чат
    dp.include_router(rating.router)    # Рейтинг

    # --- Запуск ---
    await bot.delete_webhook(drop_pending_updates=True)
    asyncio.create_task(background_tasks(bot))

    logger.info("🤖 Bot started! Press Ctrl+C to stop.")
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.critical(f"💀 Polling Error: {e}")
    finally:
        await bot.session.close()
        logger.info("🛑 Bot stopped.")

if __name__ == "__main__":
    try:
        # Фікс для Windows
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("👋 Stopped manually.")
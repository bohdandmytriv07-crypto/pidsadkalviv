import asyncio
import logging
import sys
from datetime import datetime
import pytz

from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# 🔥 Імпорт захисту від спаму
from middlewares import AntiFloodMiddleware

# Імпорти налаштувань
from config import API_TOKEN
from database import init_db, get_connection, get_trip_passengers

# Імпорти хендлерів
from handlers import common, passenger, driver, admin, profile, chat, rating
# Імпорт функції для запуску рейтингу
from handlers.rating import ask_for_ratings 

# Налаштування логування
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

async def on_startup():
    """Дії при запуску бота"""
    logger.info("🚀 Ініціалізація бази даних...")
    init_db()
    logger.info("✅ База даних готова!")

async def background_tasks(bot: Bot):
    """
    Фоновий процес, який працює вічно.
    1. Архівує старі поїздки (active -> finished).
    2. Запускає систему рейтингу для завершених поїздок.
    3. Чистить історію чатів для безпеки.
    """
    logger.info("🕒 Планувальник фонових задач запущено.")
    kyiv_tz = pytz.timezone('Europe/Kyiv')
    
    while True:
        try:
            # Чекаємо 5 хвилин між перевірками
            await asyncio.sleep(300) 
            
            conn = get_connection()
            cursor = conn.cursor()
            
            now = datetime.now(kyiv_tz)
            current_time = now.time()
            current_date = now.date()
            
            # --- ЗАДАЧА 1: АРХІВАЦІЯ СТАРИХ ПОЇЗДОК ---
            # 🔥 Додано user_id, щоб знати водія
            rows = cursor.execute("SELECT id, user_id, date, time FROM trips WHERE status='active'").fetchall()
            archived_count = 0
            
            for row in rows:
                try:
                    should_finish = False
                    
                    # Парсинг дати
                    date_parts = row['date'].split('.')
                    if len(date_parts) != 2: continue
                        
                    trip_year = now.year
                    trip_day = int(date_parts[0])
                    trip_month = int(date_parts[1])
                    
                    trip_dt = datetime(trip_year, trip_month, trip_day).date()
                    
                    # 1. Дата минула
                    if trip_dt < current_date:
                        should_finish = True
                    # 2. Дата сьогодні, але час минув
                    elif trip_dt == current_date:
                        trip_time = datetime.strptime(row['time'], "%H:%M").time()
                        if current_time > trip_time:
                            should_finish = True

                    if should_finish:
                        trip_id = row['id']
                        driver_id = row['user_id']
                        
                        # Отримуємо пасажирів ПЕРЕД закриттям
                        passengers = get_trip_passengers(trip_id)
                        
                        # Закриваємо поїздку
                        cursor.execute("UPDATE trips SET status='finished' WHERE id=?", (trip_id,))
                        conn.commit() # Зберігаємо одразу
                        
                        archived_count += 1
                        
                        # 🔥 ЗАПУСКАЄМО РЕЙТИНГ (Асинхронно)
                        if passengers:
                            asyncio.create_task(ask_for_ratings(bot, trip_id, driver_id, passengers))

                except ValueError:
                    continue 
            
            if archived_count > 0:
                logger.info(f"🧹 Архівовано {archived_count} старих поїздок.")

            # --- ЗАДАЧА 2: ОЧИЩЕННЯ БЕЗПЕКИ ---
            
            # Видаляємо історію чатів, старшу за 48 годин
            cursor.execute("DELETE FROM chat_history WHERE timestamp < datetime('now', '-2 days')")
            deleted_msgs = cursor.rowcount
            
            # Видаляємо старі поїздки з бази повністю через 30 днів
            cursor.execute("DELETE FROM trips WHERE status='finished' AND date < date('now', '-30 days')")
            deleted_trips = cursor.rowcount

            if deleted_msgs > 0 or deleted_trips > 0:
                conn.commit()
                logger.info(f"🛡️ Безпека: Видалено {deleted_msgs} повідомлень та {deleted_trips} древніх поїздок.")
            
            conn.close()

        except Exception as e:
            logger.error(f"⚠️ Помилка у фоновій задачі: {e}")
            await asyncio.sleep(60)

# Глобальний обробник помилок
async def global_error_handler(event: types.ErrorEvent):
    logger.exception(f"🔥 Критична помилка обробки: {event.exception}")
    return True

async def main():
    # Пауза для стабілізації мережі (якщо були помилки DNS)
    await asyncio.sleep(1)

    bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    # 🔥 Middleware (Захист від спаму)
    dp.message.middleware(AntiFloodMiddleware(limit=0.7))
    dp.callback_query.middleware(AntiFloodMiddleware(limit=0.5))

    # Реєстрація роутерів
    dp.include_router(admin.router)
    dp.include_router(common.router)
    dp.include_router(profile.router)
    dp.include_router(driver.router)
    dp.include_router(passenger.router)
    dp.include_router(chat.router)
    dp.include_router(rating.router) # ⭐ Рейтинг

    dp.errors.register(global_error_handler)

    await on_startup()
    await bot.delete_webhook(drop_pending_updates=True)
    
    # Запуск фону
    asyncio.create_task(background_tasks(bot))

    logger.info("🤖 Бот запущено! Натисни Ctrl+C для зупинки.")
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"💀 Критична помилка Polling: {e}")
    finally:
        await bot.session.close()
        logger.info("Бот зупинений.")

if __name__ == "__main__":
    try:
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("🛑 Бот зупинений користувачем.")
import asyncio
import logging
import sys
from datetime import datetime
import pytz
from handlers import rating
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# 🔥 Імпорт захисту від спаму
# Переконайся, що файл middlewares.py існує поруч
from middlewares import AntiFloodMiddleware

# Імпорти налаштувань
from config import API_TOKEN
from database import init_db, get_connection

# Імпорти хендлерів (твої файли)
from handlers import common, passenger, driver, admin, profile, chat

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
    2. Чистить історію чатів для безпеки.
    """
    logger.info("🕒 Планувальник фонових задач запущено.")
    kyiv_tz = pytz.timezone('Europe/Kyiv')
    
    while True:
        try:
            # Чекаємо 5 хвилин між перевірками
            await asyncio.sleep(300) 
            
            conn = get_connection()
            cursor = conn.cursor()
            
            # Отримуємо поточний час у Києві
            now = datetime.now(kyiv_tz)
            current_time = now.time()
            current_date = now.date()
            
            # --- ЗАДАЧА 1: АРХІВАЦІЯ СТАРИХ ПОЇЗДОК ---
            rows = cursor.execute("SELECT id, date, time FROM trips WHERE status='active'").fetchall()
            archived_count = 0
            
            for row in rows:
                try:
                    # Дата у форматі "ДД.ММ" (наприклад, 21.01)
                    date_parts = row['date'].split('.')
                    if len(date_parts) != 2:
                        continue
                        
                    trip_day = int(date_parts[0])
                    trip_month = int(date_parts[1])
                    trip_year = now.year
                    
                    # Створюємо об'єкт дати поїздки
                    trip_datetime = datetime(trip_year, trip_month, trip_day)
                    trip_date = trip_datetime.date()
                    
                    # 1. Якщо дата поїздки вже минула (була вчора або раніше)
                    if trip_date < current_date:
                        cursor.execute("UPDATE trips SET status='finished' WHERE id=?", (row['id'],))
                        archived_count += 1
                        
                    # 2. Якщо поїздка сьогодні, але час вже минув
                    elif trip_date == current_date:
                        trip_time = datetime.strptime(row['time'], "%H:%M").time()
                        if current_time > trip_time:
                             cursor.execute("UPDATE trips SET status='finished' WHERE id=?", (row['id'],))
                             archived_count += 1

                except ValueError:
                    continue 
            
            if archived_count > 0:
                logger.info(f"🧹 Архівовано {archived_count} старих поїздок.")

            # --- ЗАДАЧА 2: ОЧИЩЕННЯ БЕЗПЕКИ (Data Minimization) ---
            
            # Видаляємо історію чатів, старшу за 48 годин
            cursor.execute("DELETE FROM chat_history WHERE timestamp < datetime('now', '-2 days')")
            deleted_msgs = cursor.rowcount
            
            # Видаляємо завершені поїздки, старші за 30 днів
            cursor.execute("DELETE FROM trips WHERE status='finished' AND date < date('now', '-30 days')")
            deleted_trips = cursor.rowcount

            if archived_count > 0 or deleted_msgs > 0 or deleted_trips > 0:
                conn.commit()
                if deleted_msgs > 0 or deleted_trips > 0:
                    logger.info(f"🛡️ Безпека: Видалено {deleted_msgs} повідомлень та {deleted_trips} старих поїздок.")
            
            conn.close()

        except Exception as e:
            logger.error(f"⚠️ Помилка у фоновій задачі: {e}")
            await asyncio.sleep(60) # Чекаємо хвилину і пробуємо знову

# Глобальний обробник помилок
async def global_error_handler(event: types.ErrorEvent):
    """Ловить критичні помилки, щоб бот не падав."""
    logger.exception(f"🔥 Критична помилка обробки: {event.exception}")
    return True

async def main():
    # Ініціалізація бота
    bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    # 🔥 ПІДКЛЮЧЕННЯ ЗАХИСТУ ВІД СПАМУ (Middleware)
    # limit=0.7 - затримка 0.7 секунди між повідомленнями
    dp.message.middleware(AntiFloodMiddleware(limit=0.7))
    dp.callback_query.middleware(AntiFloodMiddleware(limit=0.5))

    # Реєстрація роутерів (Порядок важливий!)
    dp.include_router(admin.router)      # Адмінка
    dp.include_router(common.router)     # Загальні команди (/start)
    dp.include_router(profile.router)    # Профіль
    dp.include_router(driver.router)     # Водій
    dp.include_router(passenger.router)  # Пасажир
    dp.include_router(chat.router)       # Чат система
    dp.include_router(rating.router)

    # Реєстрація обробника помилок
    dp.errors.register(global_error_handler)

    # Запуск бази даних
    await on_startup()

    # Видалення вебхуків (для локального запуску)
    await bot.delete_webhook(drop_pending_updates=True)

    # Запуск фонових задач
    asyncio.create_task(background_tasks(bot))

    # Старт бота
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
        # Оптимізація для Windows
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("🛑 Бот зупинений користувачем.")
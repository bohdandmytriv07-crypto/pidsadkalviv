import asyncio
import logging
import sys
import os
import sentry_sdk
from datetime import datetime
import pytz
from logging.handlers import RotatingFileHandler
from aiohttp import ClientSession
# Імпорт для налаштування проксі (для PythonAnywhere)
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import ChatMemberUpdatedFilter, KICKED, MEMBER
from aiogram.types import ChatMemberUpdated

# Middleware
from middlewares import AntiFloodMiddleware, ActivityMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from database import get_bookings_to_remind, mark_booking_reminded
from config import API_TOKEN 
from database import (
    init_db, set_user_blocked_bot, 
    perform_db_cleanup, archive_old_trips_db, 
    mark_trip_finished, get_trip_passengers
)

# Імпорти хендлерів
from handlers import common, passenger, driver, admin, profile, chat, rating
from handlers.rating import ask_for_ratings 
SENTRY_DSN="https://6721cc67cfc35dbdcd147955722559c4@o4510807075782656.ingest.de.sentry.io/4510807089741904"
# ==========================================
# ⚙️ НАЛАШТУВАННЯ ЛОГУВАННЯ
# ==========================================
def setup_logging():
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    # Створюємо файл логів (максимум 5 МБ)
    file_handler = RotatingFileHandler("bot.log", maxBytes=5*1024*1024, backupCount=1, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logging.basicConfig(level=logging.INFO, handlers=[console_handler, file_handler])

logger = logging.getLogger(__name__)

# ==========================================
# 🕒 ФОНОВІ ЗАДАЧІ (NON-BLOCKING)
# ==========================================
async def background_tasks(bot: Bot):
    logger.info("🕒 Планувальник фонових задач запущено.")
    
    kyiv_tz = pytz.timezone('Europe/Kyiv')
    
    while True:
        try:
            await asyncio.sleep(600)  # Перевірка раз на 10 хв
            
            # Отримуємо старі поїздки з бази
            active_trips = await asyncio.to_thread(archive_old_trips_db)
            
            now = datetime.now(kyiv_tz)
            archived_count = 0
            
            for row in active_trips:
                try:
                    # Формуємо дату, підставляючи ПОТОЧНИЙ рік
                    trip_dt_str = f"{row['date']}.{now.year}"
                    trip_full_dt = datetime.strptime(f"{trip_dt_str} {row['time']}", "%d.%m.%Y %H:%M")
                    
                    # Локалізуємо час (додаємо часовий пояс Києва)
                    trip_full_dt = kyiv_tz.localize(trip_full_dt)

                    # 🔥 ФІКС НОВОГО РОКУ:
                    # Якщо сформована дата (наприклад, грудень 2026) випереджає поточну (січень 2026)
                    # більше ніж на 180 днів — значить, це насправді поїздка з МИНУЛОГО року (грудень 2025).
                    if (trip_full_dt - now).days > 180:
                        trip_full_dt = trip_full_dt.replace(year=now.year - 1)

                    # Якщо розрахований час поїздки вже минув
                    if trip_full_dt < now:
                        trip_id = row['id']
                        driver_id = row['user_id']
                        
                        # Позначаємо як завершену
                        await asyncio.to_thread(mark_trip_finished, trip_id)
                        
                        # Отримуємо пасажирів і просимо рейтинг
                        passengers = await asyncio.to_thread(get_trip_passengers, trip_id)
                        if passengers:
                            asyncio.create_task(ask_for_ratings(bot, trip_id, driver_id, passengers))
                        
                        archived_count += 1
                except ValueError: 
                    continue 
            
            if archived_count > 0:
                logger.info(f"🏁 Завершено автоматично {archived_count} поїздок.")

            # Очистка старих записів з бази
            await asyncio.to_thread(perform_db_cleanup)
            logger.info("♻️ Очистка бази виконана.")

        except Exception as e:
            logger.error(f"⚠️ Background Task Error: {e}")
            await asyncio.sleep(60)
class PythonAnywhereSession(AiohttpSession):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def create_session(self) -> ClientSession:
        # 🔥 ВИПРАВЛЕНО: Прибрали json_deserialize, бо він викликав помилку
        return ClientSession(trust_env=True, json_serialize=self.json_dumps)
# ==========================================
# 🚫 ОБРОБКА БЛОКУВАНЬ КОРИСТУВАЧАМИ
# ==========================================
async def on_user_block(event: ChatMemberUpdated):
    user_id = event.from_user.id
    if event.new_chat_member.status == KICKED:
        logger.info(f"User {user_id} blocked bot.")
        await asyncio.to_thread(set_user_blocked_bot, user_id, True)
    elif event.new_chat_member.status == MEMBER:
        logger.info(f"User {user_id} unblocked bot.")
        await asyncio.to_thread(set_user_blocked_bot, user_id, False)

async def global_error_handler(event: types.ErrorEvent):
    logger.exception(f"🔥 Critical Update Error: {event.exception}")
    return True
async def check_reminders_job(bot: Bot):
    try:
        bookings = await asyncio.to_thread(get_bookings_to_remind)
        kyiv_tz = pytz.timezone('Europe/Kyiv')
        now = datetime.now(kyiv_tz)
        
        for b in bookings:
            try:
                # Парсимо час поїздки
                trip_dt_str = f"{b['date']}.{now.year} {b['time']}"
                trip_dt = datetime.strptime(trip_dt_str, "%d.%m.%Y %H:%M")
                trip_dt = kyiv_tz.localize(trip_dt)
                
                # Якщо зараз січень, а поїздка в грудні - віднімаємо рік (фікс переходу року)
                if (trip_dt - now).days > 180:
                    trip_dt = trip_dt.replace(year=now.year - 1)
                
                # Різниця в часі
                diff = (trip_dt - now).total_seconds()
                
                # Якщо до поїздки від 30 хв до 90 хв (нагадуємо за годину)
                if 1800 < diff < 5400:
                    # Надсилаємо нагадування пасажиру
                    text = f"⏰ <b>Нагадування!</b>\nЧерез годину ({b['time']}) поїздка: {b['origin']} ➝ {b['destination']}."
                    await bot.send_message(b['passenger_id'], text)
                    
                    # Позначаємо в базі, щоб не слати двічі
                    await asyncio.to_thread(mark_booking_reminded, b['id'])
                    
            except Exception as e:
                print(f"Reminder Error for {b['id']}: {e}")
                continue
                
    except Exception as e:
        logger.error(f"Scheduler Error: {e}")
# ==========================================
# 🚀 MAIN FUNCTION
# ==========================================
async def main():
    setup_logging()
    
    logger.info("🚀 Ініціалізація бази даних...")
    # Ініціалізація бази даних
    init_db()
    logger.info("✅ База даних готова (WAL mode on)!")

    # --- 🔥 НАЛАШТУВАННЯ ПРОКСІ ДЛЯ СЕРВЕРА 🔥 ---
    # Перевіряємо, чи ми на PythonAnywhere (вони мають цю змінну середовища)
    if os.getenv("PYTHONANYWHERE_DOMAIN"):
        logger.info("🌐 Запуск на сервері PythonAnywhere (Native Proxy)")
        # Використовуємо наш кастомний клас, без явного вказання proxy="..."
        session = PythonAnywhereSession()
        bot = Bot(token=API_TOKEN, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    else:
        logger.info("💻 Запуск локально (пряме з'єднання)")
        bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    dp = Dispatcher(storage=MemoryStorage())

    # Middleware
    dp.message.middleware(ActivityMiddleware())
    dp.callback_query.middleware(ActivityMiddleware())
    dp.message.middleware(AntiFloodMiddleware(limit=0.7))
    dp.callback_query.middleware(AntiFloodMiddleware(limit=0.5))

    # Реєстрація хендлерів блокування
    dp.my_chat_member.register(on_user_block, ChatMemberUpdatedFilter(member_status_changed=KICKED | MEMBER))
    dp.errors.register(global_error_handler)

    # Підключення роутерів (хендлерів)
    dp.include_router(admin.router)
    dp.include_router(common.router)
    dp.include_router(profile.router)
    dp.include_router(driver.router)
    dp.include_router(passenger.router)
    dp.include_router(chat.router)
    dp.include_router(rating.router)

 
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_reminders_job, 'interval', minutes=2, kwargs={'bot': bot})
    scheduler.start()
    
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
        # Спеціальний фікс для Windows (щоб не було помилок при закритті локально)
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("👋 Stopped manually.")
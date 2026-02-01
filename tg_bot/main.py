import asyncio
import logging
import sys
import os
import sentry_sdk
from datetime import datetime
import pytz
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import ChatMemberUpdatedFilter, KICKED, MEMBER
from aiogram.types import ChatMemberUpdated
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# 👇 Імпортуємо налаштування (переконайся, що в config.py є SENTRY_DSN)
from config import API_TOKEN, SENTRY_DSN

# Імпорти модулів проекту
from middlewares import AntiFloodMiddleware, ActivityMiddleware
from database import (
    init_db, set_user_blocked_bot, 
    perform_db_cleanup, archive_old_trips_db, 
    mark_trip_finished, get_trip_passengers,
    get_bookings_to_remind, mark_booking_reminded
)

# Імпорти хендлерів
from handlers import common, passenger, driver, admin, profile, chat, rating
from handlers.rating import ask_for_ratings 

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

    # Підключення Sentry (якщо є ключ в config.py)
    if SENTRY_DSN:
        sentry_sdk.init(
            dsn=SENTRY_DSN,
            traces_sample_rate=1.0,
            profiles_sample_rate=1.0,
        )
        logging.info("✅ Sentry успішно підключено! Помилки будуть відслідковуватись.")
    else:
        logging.warning("⚠️ SENTRY_DSN не знайдено. Логування в Sentry вимкнено.")

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
                    # Формуємо дату
                    trip_dt_str = f"{row['date']}.{now.year}"
                    trip_full_dt = datetime.strptime(f"{trip_dt_str} {row['time']}", "%d.%m.%Y %H:%M")
                    trip_full_dt = kyiv_tz.localize(trip_full_dt)

                    # 🔥 FIX: Розумне визначення року
                    # Рахуємо різницю в днях
                    diff_days = (trip_full_dt - now).days

                    # 1. Якщо поїздка "в далекому майбутньому" (> 6 міс), значить це був минулий рік
                    # (наприклад: зараз Січень, а дата "25.12" парситься як наступний грудень)
                    if diff_days > 180:
                        trip_full_dt = trip_full_dt.replace(year=now.year - 1)
                    
                    # 2. Якщо поїздка "в далекому минулому" (< -6 міс), значить це наступний рік
                    # (наприклад: зараз Грудень, а дата "01.01" парситься як минулий січень)
                    elif diff_days < -180:
                        trip_full_dt = trip_full_dt.replace(year=now.year + 1)

                    # Якщо час поїздки вже минув
                    if trip_full_dt < now:
                        trip_id = row['id']
                        driver_id = row['user_id']
                        
                        # Завершуємо
                        await asyncio.to_thread(mark_trip_finished, trip_id)
                        
                        # Просимо рейтинг
                        passengers = await asyncio.to_thread(get_trip_passengers, trip_id)
                        if passengers:
                            asyncio.create_task(ask_for_ratings(bot, trip_id, driver_id, passengers))
                        
                        archived_count += 1
                except ValueError: 
                    continue 
            
            if archived_count > 0:
                logger.info(f"🏁 Завершено автоматично {archived_count} поїздок.")

            # Очистка сміття в базі
            await asyncio.to_thread(perform_db_cleanup)
            logger.info("♻️ Очистка бази виконана.")

        except Exception as e:
            logger.exception(f"⚠️ Background Task Error") # 🔥 Покаже повний трейсбек
            await asyncio.sleep(60)

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
                trip_dt_str = f"{b['date']}.{now.year} {b['time']}"
                trip_dt = datetime.strptime(trip_dt_str, "%d.%m.%Y %H:%M")
                trip_dt = kyiv_tz.localize(trip_dt)
                
                # 🔥 FIX: Така сама логіка років, як і в background_tasks
                diff_days = (trip_dt - now).days
                if diff_days > 180:
                    trip_dt = trip_dt.replace(year=now.year - 1)
                elif diff_days < -180:
                    trip_dt = trip_dt.replace(year=now.year + 1)
                
                diff = (trip_dt - now).total_seconds()
                
                # Нагадуємо за 1 годину (діапазон 30-90 хв)
                if 1800 < diff < 5400:
                    text = f"⏰ <b>Нагадування!</b>\nЧерез годину ({b['time']}) поїздка: {b['origin']} ➝ {b['destination']}."
                    await bot.send_message(b['passenger_id'], text)
                    await asyncio.to_thread(mark_booking_reminded, b['id'])
                    
            except Exception as e:
                logger.error(f"Reminder Error for {b['id']}: {e}")
                continue
                
    except Exception as e:
        logger.error(f"Scheduler Error: {e}")

# ==========================================
# 🚀 MAIN FUNCTION
# ==========================================
async def main():
    setup_logging()
    
    logger.info("🚀 Ініціалізація бази даних...")
    init_db()
    logger.info("✅ База даних готова (WAL mode on)!")

    # Стандартна ініціалізація бота
    logger.info("💻 Запуск бота (VPS Mode)...")
    bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    dp = Dispatcher(storage=MemoryStorage())

    # Middleware
    dp.message.middleware(ActivityMiddleware())
    dp.callback_query.middleware(ActivityMiddleware())
    dp.message.middleware(AntiFloodMiddleware(limit=0.7))
    dp.callback_query.middleware(AntiFloodMiddleware(limit=0.5))

    # Реєстрація хендлерів подій
    dp.my_chat_member.register(on_user_block, ChatMemberUpdatedFilter(member_status_changed=KICKED | MEMBER))
    dp.errors.register(global_error_handler)

    # Підключення роутерів
    dp.include_router(admin.router)
    dp.include_router(common.router)
    dp.include_router(profile.router)
    dp.include_router(driver.router)
    dp.include_router(passenger.router)
    dp.include_router(chat.router)
    dp.include_router(rating.router)

    # Планувальник завдань
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_reminders_job, 'interval', minutes=2, kwargs={'bot': bot})
    scheduler.start()
    
    # 🔥 FIX: Прибрали drop_pending_updates=True, щоб не губити повідомлення при рестарті
    await bot.delete_webhook()
    
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
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("👋 Stopped manually.")
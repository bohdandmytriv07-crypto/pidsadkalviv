import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta
from handlers.admin import router as admin_router
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage


from config import API_TOKEN
from database import (
    init_db, 
    get_all_active_trips, 
    finish_trip, 
    get_trip_passengers, 
    mark_trip_notified
)
from middlewares import ThrottlingMiddleware

# 👇 ВИПРАВЛЕНО: Додано "handlers." до шляхів імпорту
from handlers.common import router as common_router
from handlers.profile import router as profile_router
from handlers.driver import router as driver_router
from handlers.passenger import router as passenger_router
from handlers.chat import router as chat_router

# ==========================================
# ⚙️ НАЛАШТУВАННЯ ЛОГУВАННЯ
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


# ==========================================
# 🕒 ФОНОВА ЗАДАЧА (CRON)
# ==========================================
async def check_trips_periodically(bot: Bot):
    """
    Періодично перевіряє активні поїздки:
    1. Надсилає нагадування за 1 годину.
    2. Завершує поїздки через 1 годину після старту.
    """
    logger.info("🕒 Фонова перевірка поїздок запущена.")
    while True:
        try:
            trips = get_all_active_trips()
            now = datetime.now()
            
            for trip in trips:
                try:
                    date_parts = trip['date'].split('.')
                    if len(date_parts) != 2: continue
                        
                    day = int(date_parts[0])
                    month = int(date_parts[1])
                    year = now.year
                    if now.month == 12 and month == 1: year += 1
                    
                    trip_full_str = f"{day:02d}.{month:02d}.{year} {trip['time']}"
                    trip_dt = datetime.strptime(trip_full_str, "%d.%m.%Y %H:%M")
                    
                    time_diff_minutes = (trip_dt - now).total_seconds() / 60

                    # 1. СПОВІЩЕННЯ (за 60 хв)
                    if 0 < time_diff_minutes <= 60 and trip['is_notified'] == 0:
                        logger.info(f"🔔 Сповіщення для поїздки {trip['id']}")
                        
                        passengers = get_trip_passengers(trip['id'])
                        for p in passengers:
                            try:
                                await bot.send_message(
                                    chat_id=p['user_id'],
                                    text=f"⏰ <b>Нагадування!</b>\nПоїздка до <b>{trip['destination']}</b> через годину ({trip['time']}).",
                                    parse_mode="HTML"
                                )
                            except Exception: pass
                        
                        try:
                            await bot.send_message(
                                chat_id=trip['user_id'],
                                text=f"⏰ <b>Нагадування!</b>\nПоїздка до <b>{trip['destination']}</b> стартує через годину.",
                                parse_mode="HTML"
                            )
                        except Exception: pass

                        mark_trip_notified(trip['id'])

                    # 2. АВТО-ЗАВЕРШЕННЯ
                    if time_diff_minutes < -60:
                        finish_trip(trip['id'])
                        logger.info(f"🏁 Поїздка {trip['id']} автоматично завершена.")

                except ValueError: continue
                except Exception as e: logger.error(f"Error trip {trip.get('id')}: {e}")

        except Exception as e:
            logger.error(f"Global loop error: {e}")

        await asyncio.sleep(60)


# ==========================================
# 🚀 ГОЛОВНА ФУНКЦІЯ
# ==========================================
async def main():
    init_db()
    
    bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    dp.message.middleware(ThrottlingMiddleware())
    dp.callback_query.middleware(ThrottlingMiddleware())

    # Реєстрація роутерів
    dp.include_router(admin_router)
    dp.include_router(common_router)
    dp.include_router(profile_router)
    dp.include_router(driver_router)
    dp.include_router(passenger_router)
    dp.include_router(chat_router)      

    await bot.delete_webhook(drop_pending_updates=True)
    asyncio.create_task(check_trips_periodically(bot))

    logger.info("✅ Бот успішно запущено!")
    
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Error: {e}")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped.")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        RotatingFileHandler("bot.log", maxBytes=5*1024*1024, backupCount=2), # 5 MB на файл
        logging.StreamHandler(sys.stdout)
    ]
)
import asyncio
import logging
import sys
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

# --- ІМПОРТИ З ВАШОГО ПРОЕКТУ ---
from config import API_TOKEN
from database import (
    init_db, 
    get_all_active_trips, 
    finish_trip, 
    get_trip_passengers, 
    mark_trip_notified
)
from middlewares import ThrottlingMiddleware

# Імпорт хендлерів (роутерів)
from handlers import common, profile, driver, passenger, chat

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

                    # 1. Сповіщення (за 60 хв)
                    if 0 < time_diff_minutes <= 60 and trip['is_notified'] == 0:
                        logger.info(f"🔔 Сповіщення для поїздки {trip['id']}")
                        
                        # Пасажирам
                        passengers = get_trip_passengers(trip['id'])
                        for p in passengers:
                            try:
                                await bot.send_message(
                                    chat_id=p['user_id'],
                                    text=f"⏰ <b>Нагадування!</b>\nПоїздка до <b>{trip['destination']}</b> через годину ({trip['time']}).",
                                    parse_mode="HTML"
                                )
                            except Exception: pass
                        
                        # Водію
                        try:
                            await bot.send_message(
                                chat_id=trip['user_id'],
                                text=f"⏰ <b>Нагадування!</b>\nПоїздка до <b>{trip['destination']}</b> стартує через годину.",
                                parse_mode="HTML"
                            )
                        except Exception: pass

                        mark_trip_notified(trip['id'])

                    # 2. Закриття (через 1 годину після старту)
                    if trip_dt + timedelta(hours=1) < now:
                        finish_trip(trip['id'])
                        logger.info(f"🏁 Поїздка {trip['id']} завершена.")

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
    
    bot = Bot(token=API_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    # Підключення Middleware
    dp.message.middleware(ThrottlingMiddleware())
    dp.callback_query.middleware(ThrottlingMiddleware())

    # --- РЕЄСТРАЦІЯ РОУТЕРІВ (ПОРЯДОК ВАЖЛИВИЙ!) ---
    
    # 1. Загальні команди (/start, /help) - мають спрацьовувати першими
    dp.include_router(common.router)
    
    # 2. Специфічні меню (профіль, водій, пасажир) - перехоплюють введення даних
    dp.include_router(profile.router)
    dp.include_router(driver.router)
    dp.include_router(passenger.router)
    
    # 3. Чат - ловить все інше (текст переписки)
    # Якщо поставити його вище, він буде "з'їдати" команди і введення міст
    dp.include_router(chat.router)       

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



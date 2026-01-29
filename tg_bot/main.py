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

# Middleware
from middlewares import AntiFloodMiddleware, ActivityMiddleware

from config import API_TOKEN 
from database import (
    init_db, set_user_blocked_bot, 
    perform_db_cleanup, archive_old_trips_db, 
    mark_trip_finished, get_trip_passengers
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
            # Чекаємо 10 хвилин
            await asyncio.sleep(600) 
            
            # 1. АРХІВАЦІЯ (В окремому потоці, щоб не блокувати)
            # Отримуємо кандидатів на архівацію
            active_trips = await asyncio.to_thread(archive_old_trips_db)
            
            now = datetime.now(kyiv_tz)
            archived_count = 0
            
            for row in active_trips:
                try:
                    trip_dt_str = f"{row['date']}.{now.year}"
                    trip_full_dt = datetime.strptime(f"{trip_dt_str} {row['time']}", "%d.%m.%Y %H:%M")
                    trip_full_dt = kyiv_tz.localize(trip_full_dt)

                    if trip_full_dt < now:
                        trip_id = row['id']
                        driver_id = row['user_id']
                        
                        # Пишемо в базу (Thread Safe)
                        await asyncio.to_thread(mark_trip_finished, trip_id)
                        
                        # Рейтинг (це асинхронно, все ок)
                        passengers = await asyncio.to_thread(get_trip_passengers, trip_id)
                        if passengers:
                            asyncio.create_task(ask_for_ratings(bot, trip_id, driver_id, passengers))
                        
                        archived_count += 1
                except ValueError: continue 
            
            if archived_count > 0:
                logger.info(f"🏁 Завершено {archived_count} поїздок.")

            # 2. ГЕНЕРАЛЬНЕ ПРИБИРАННЯ (Thread Safe)
            await asyncio.to_thread(perform_db_cleanup)
            logger.info("♻️ Очистка бази виконана.")

        except Exception as e:
            logger.error(f"⚠️ Background Task Error: {e}")
            await asyncio.sleep(60)

# ==========================================
# 🚫 ОБРОБКА БЛОКУВАНЬ
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

# ==========================================
# 🚀 MAIN FUNCTION
# ==========================================
async def main():
    setup_logging()
    
    logger.info("🚀 Ініціалізація бази даних...")
    # Init DB можна запускати синхронно на старті
    init_db()
    logger.info("✅ База даних готова (WAL mode on)!")

    bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    # Middleware
    dp.message.middleware(ActivityMiddleware())
    dp.callback_query.middleware(ActivityMiddleware())
    dp.message.middleware(AntiFloodMiddleware(limit=0.7))
    dp.callback_query.middleware(AntiFloodMiddleware(limit=0.5))

    dp.my_chat_member.register(on_user_block, ChatMemberUpdatedFilter(member_status_changed=KICKED | MEMBER))
    dp.errors.register(global_error_handler)

    # Routers
    dp.include_router(admin.router)
    dp.include_router(common.router)
    dp.include_router(profile.router)
    dp.include_router(driver.router)
    dp.include_router(passenger.router)
    dp.include_router(chat.router)
    dp.include_router(rating.router)

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
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("👋 Stopped manually.")

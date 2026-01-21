import asyncio
import logging
import sys
from datetime import datetime, timedelta
import pytz

from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# Configuration imports
from config import API_TOKEN, DB_FILE
from database import init_db, get_connection

# Handler imports
from handlers import common, passenger, driver, admin, profile, chat

# ⚙️ Logging Configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

async def on_startup():
    """
    Actions performed once at bot startup.
    """
    logger.info("🚀 Initializing database...")
    init_db()
    logger.info("✅ Database ready!")

async def background_tasks(bot: Bot):
    """
    Background daemon process that runs indefinitely.
    It handles:
    1. Archiving old trips (active -> finished).
    2. Security cleanup (deleting old chat history and trip records).
    """
    logger.info("🕒 Background task scheduler started.")
    kyiv_tz = pytz.timezone('Europe/Kyiv')
    
    while True:
        try:
            # 1. Wait 5 minutes (300 seconds) between checks
            await asyncio.sleep(300) 
            
            conn = get_connection()
            cursor = conn.cursor()
            
            # Get current time in Kyiv
            now = datetime.now(kyiv_tz)
            current_time = now.time()
            
            # --- TASK 1: ARCHIVE OLD TRIPS ---
            rows = cursor.execute("SELECT id, date, time FROM trips WHERE status='active'").fetchall()
            archived_count = 0
            
            for row in rows:
                try:
                    trip_day, trip_month = map(int, row['date'].split('.'))
                    trip_year = now.year
                    
                    trip_datetime = datetime(trip_year, trip_month, trip_day)
                    
                    # If trip was yesterday or earlier
                    if trip_datetime.date() < now.date():
                        cursor.execute("UPDATE trips SET status='finished' WHERE id=?", (row['id'],))
                        archived_count += 1
                        
                    # If trip is today but time has passed
                    elif trip_datetime.date() == now.date():
                        trip_time = datetime.strptime(row['time'], "%H:%M").time()
                        if current_time > trip_time:
                             cursor.execute("UPDATE trips SET status='finished' WHERE id=?", (row['id'],))
                             archived_count += 1

                except ValueError:
                    continue 
            
            if archived_count > 0:
                conn.commit()
                logger.info(f"🧹 Archived {archived_count} old trips.")

            # --- TASK 2: SECURITY CLEANUP (DATA MINIMIZATION) ---
            # Delete chat history older than 48 hours to protect privacy
            cursor.execute("DELETE FROM chat_history WHERE timestamp < datetime('now', '-2 days')")
            deleted_msgs = cursor.rowcount
            
            # Delete finished trips older than 30 days
            cursor.execute("DELETE FROM trips WHERE status='finished' AND date < date('now', '-30 days')")
            deleted_trips = cursor.rowcount

            if deleted_msgs > 0 or deleted_trips > 0:
                conn.commit()
                logger.info(f"🛡️ Security Cleanup: Deleted {deleted_msgs} old messages and {deleted_trips} old trips.")
            
            conn.close()

        except Exception as e:
            logger.error(f"⚠️ Error in background task: {e}")
            await asyncio.sleep(60) # Wait a minute and try again

# 🛡️ Global Error Handler
async def global_error_handler(event: types.ErrorEvent):
    """
    Catches any critical errors in handlers to prevent the bot from crashing.
    """
    logger.exception(f"🔥 Critical processing error: {event.exception}")
    return True

async def main():
    # Bot and Dispatcher initialization
    bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    # Register Routers (Order matters!)
    dp.include_router(admin.router)      # Admin functionality first
    dp.include_router(common.router)     # Common commands
    dp.include_router(profile.router)    # Profiles
    dp.include_router(driver.router)     # Driver functionality
    dp.include_router(passenger.router)  # Passenger functionality
    dp.include_router(chat.router)       # Chat system

    # Register Error Handler
    dp.errors.register(global_error_handler)

    # Database startup
    await on_startup()

    # Clear webhooks
    await bot.delete_webhook(drop_pending_updates=True)

    # Start background tasks
    asyncio.create_task(background_tasks(bot))

    # Start Polling
    logger.info("🤖 Bot started! Press Ctrl+C to stop.")
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"💀 Critical Polling Error: {e}")
    finally:
        await bot.session.close()
        logger.info("Bot stopped.")

if __name__ == "__main__":
    try:
        # Windows optimization
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("🛑 Bot stopped by user.")
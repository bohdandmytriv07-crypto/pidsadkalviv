import time
import asyncio
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery

# 👇 Імпорт функції з бази
from database import update_user_activity

# ⚡ Кеш для збереження активності (User ID -> Timestamp)
# Щоб не дьоргати базу кожну секунду
last_activity_cache = {}

class ActivityMiddleware(BaseMiddleware):
    """
    Оновлює час останньої активності користувача.
    Пише в базу не частіше, ніж раз на 5 хвилин для кожного юзера.
    """
    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any]
    ) -> Any:
        
        user = data.get("event_from_user")
        
        if user:
            current_time = time.time()
            last_update = last_activity_cache.get(user.id, 0)
            
            # 🔥 Оптимізація: Оновлюємо базу тільки якщо пройшло > 5 хв (300 сек)
            if current_time - last_update > 300:
                username = f"@{user.username}" if user.username else None
                full_name = user.full_name
                
                # Запускаємо в окремому потоці, щоб не блокувати Event Loop
                await asyncio.to_thread(update_user_activity, user.id, username, full_name)
                
                # Оновлюємо кеш
                last_activity_cache[user.id] = current_time

        return await handler(event, data)


class AntiFloodMiddleware(BaseMiddleware):
    def __init__(self, limit: float = 0.5):
        self.rate_limit = limit
        self.last_time = {}

    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any]
    ) -> Any:
        
 
        if hasattr(event, "media_group_id") and event.media_group_id:
            return await handler(event, data)

        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        current_time = time.time()
        
        if user.id in self.last_time:
            if current_time - self.last_time[user.id] < self.rate_limit:
              
                if isinstance(event, CallbackQuery):
                    await event.answer("⏳ Не тисніть так швидко!", show_alert=True)
                return 
        
        self.last_time[user.id] = current_time
        return await handler(event, data)
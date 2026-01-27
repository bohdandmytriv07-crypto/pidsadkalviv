import time
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery

# 👇 Імпорт функції з бази
from database import update_user_activity

class ActivityMiddleware(BaseMiddleware):
    """
    Оновлює час останньої активності користувача при кожній дії.
    """
    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any]
    ) -> Any:
        
        user = data.get("event_from_user")
        
        if user:
            # Отримуємо username (якщо є, інакше None)
            username = f"@{user.username}" if user.username else None
            full_name = user.full_name
            
            # 🔥 Оновлюємо базу даних (це дуже швидко у WAL режимі)
            update_user_activity(user.id, username, full_name)

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
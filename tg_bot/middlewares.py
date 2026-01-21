import time
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery

class AntiFloodMiddleware(BaseMiddleware):
    def __init__(self, limit: float = 0.5):
        """
        limit - час затримки в секундах.
        0.5 - це пів секунди. Якщо частіше - блокуємо.
        """
        self.rate_limit = limit
        self.last_time = {}

    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any]
    ) -> Any:
        
        # Отримуємо користувача, який робить дію
        user = data.get("event_from_user")
        
        # Якщо це не користувач (наприклад, канал), пропускаємо
        if not user:
            return await handler(event, data)

        current_time = time.time()
        
        # Перевіряємо, коли він писав останній раз
        if user.id in self.last_time:
            if current_time - self.last_time[user.id] < self.rate_limit:
                # ⛔ СПАМ ВИЯВЛЕНО
                
                # Якщо це натискання кнопки - показуємо спливаюче вікно
                if isinstance(event, CallbackQuery):
                    await event.answer("⏳ Не тисніть так швидко! Зачекайте.", show_alert=True)
                
                # Якщо це повідомлення - просто ігноруємо (нічого не робимо, бот мовчить)
                # Повертаємо None, щоб зупинити обробку
                return 
        
        # ✅ Все ок, оновлюємо час і пускаємо далі
        self.last_time[user.id] = current_time
        return await handler(event, data)
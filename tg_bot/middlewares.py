from typing import Any, Awaitable, Callable, Dict, Union
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject
from cachetools import TTLCache # pip install cachetools

class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, time_limit: float = 0.7):
        # time_limit = 0.7 сек достатньо, щоб відсіяти подвійні кліки, але не бісити користувача
        self.limit = TTLCache(maxsize=10000, ttl=time_limit)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        
        # Отримуємо користувача (працює і для Message, і для CallbackQuery)
        user = getattr(event, "from_user", None)

        if user:
            if user.id in self.limit:
                # Якщо це натискання кнопки, можна відповісти, щоб годинник не крутився
                if isinstance(event, CallbackQuery):
                    await event.answer("Занадто швидко!", show_alert=False)
                return # Ігноруємо апдейт
            
            self.limit[user.id] = True

        return await handler(event, data)
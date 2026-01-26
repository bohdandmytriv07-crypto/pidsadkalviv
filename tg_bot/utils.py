import re
from contextlib import suppress
from aiogram import types, Bot
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

# 👇 Бібліотеки для розумного пошуку
from thefuzz import process
from geopy.geocoders import Nominatim

# 👇 Імпорт функції, яка дістає збережені міста з твоєї бази
from database import get_all_cities_names

# 👇 Ініціалізація пошуку в інтернеті
geolocator = Nominatim(user_agent="ua_ride_bot_pidsadka")


# ==========================================
# 🧠 РОЗУМНИЙ ПОШУК (БАЗА + ІНТЕРНЕТ)
# ==========================================

def get_city_suggestion(raw_input: str) -> str | None:
    """Шукає схоже місто у ЛОКАЛЬНІЙ БАЗІ."""
    if not raw_input: return None
    
    known_cities = get_all_cities_names()
    if not known_cities: return None

    best_match = process.extractOne(raw_input, known_cities)
    
    if best_match and best_match[1] >= 75:
        return best_match[0]
            
    return None


def validate_city_real(city_name: str) -> str | None:
    """Перевіряє місто через ІНТЕРНЕТ (OpenStreetMap)."""
    try:
        location = geolocator.geocode(f"{city_name}, Ukraine", language="uk")
        if location:
            return location.address.split(',')[0]
    except Exception as e:
        print(f"⚠️ Помилка геокодера: {e}")
        return None 
    return None


def is_valid_city(text: str) -> bool:
    """Базова перевірка на спецсимволи."""
    if not text or len(text) < 2 or len(text) > 50:
        return False
    if any(char.isdigit() for char in text):
        return False
    return True


# ==========================================
# 🧹 ОЧИЩЕННЯ ТА ІНТЕРФЕЙС (CORE)
# ==========================================

async def clean_user_input(message: types.Message):
    """
    Видаляє повідомлення, яке написав користувач.
    Викликати на початку кожного хендлера, де юзер вводить текст.
    """
    with suppress(TelegramBadRequest):
        await message.delete()


async def delete_prev_msg(state: FSMContext, bot: Bot, chat_id: int):
    """
    Видаляє ОДНЕ попереднє повідомлення бота (головне меню або питання).
    """
    data = await state.get_data()
    last_msg_id = data.get("last_msg_id")
    
    if last_msg_id:
        with suppress(TelegramBadRequest):
            await bot.delete_message(chat_id=chat_id, message_id=last_msg_id)
        # Очищаємо змінну, щоб не намагатись видалити двічі
        await state.update_data(last_msg_id=None)


async def delete_messages_list(state: FSMContext, bot: Bot, chat_id: int, key: str):
    """
    🔥 НОВА ФУНКЦІЯ: Видаляє СПИСОК повідомлень.
    key - це назва ключа в state (наприклад, 'search_msg_ids'), де лежить список ID.
    """
    data = await state.get_data()
    msg_ids = data.get(key, [])
    
    if msg_ids:
        for mid in msg_ids:
            with suppress(TelegramBadRequest):
                await bot.delete_message(chat_id=chat_id, message_id=mid)
        
        # Очищаємо список у стані
        await state.update_data({key: []})


async def send_new_clean_msg(message: types.Message, state: FSMContext, text: str, kb=None):
    """
    Примусово видаляє старе -> Шле нове.
    Використовується для Reply-клавіатур або зміни розділів.
    """
    await delete_prev_msg(state, message.bot, message.chat.id)
    
    msg = await message.answer(text, reply_markup=kb, parse_mode="HTML")
    await state.update_data(last_msg_id=msg.message_id)


async def update_or_send_msg(bot: Bot, chat_id: int, state: FSMContext, text: str, kb=None):
    """
    Головна функція інтерфейсу.
    1. Пробує редагувати старе повідомлення (щоб не миготіло).
    2. Якщо не виходить (повідомлення старе/видалене) -> видаляє старе, шле нове.
    """
    data = await state.get_data()
    last_msg_id = data.get("last_msg_id")
    
    if last_msg_id:
        try:
            await bot.edit_message_text(
                text=text, 
                chat_id=chat_id, 
                message_id=last_msg_id, 
                reply_markup=kb, 
                parse_mode="HTML"
            )
            return # Успіх, виходимо
        except TelegramBadRequest:
            pass # Не вийшло редагувати
            
    # План Б: Видаляємо старе (якщо воно є) і шлемо нове
    await delete_prev_msg(state, bot, chat_id)
    
    msg = await bot.send_message(chat_id=chat_id, text=text, reply_markup=kb, parse_mode="HTML")
    await state.update_data(last_msg_id=msg.message_id)
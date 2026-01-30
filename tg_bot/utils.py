import asyncio
import re
from contextlib import suppress
from aiogram import types, Bot
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

# Бібліотеки для пошуку
from thefuzz import process
from geopy.geocoders import Nominatim
from database import get_all_cities_names

# Налаштування Nominatim (User-Agent обов'язковий!)
geolocator = Nominatim(
    user_agent="pidsadka_lviv_bot_v2_admin_contact", 
    timeout=10
)

# ==========================================
# 🧹 МАГІЯ ОЧИЩЕННЯ (UI ENGINE)
# ==========================================

async def clean_user_input(message: types.Message):
    """Видаляє повідомлення, яке написав користувач."""
    try:
        await message.delete()
    except Exception:
        pass

async def delete_prev_msg(state: FSMContext, bot: Bot, chat_id: int):
    """Примусово видаляє останнє повідомлення бота."""
    data = await state.get_data()
    last_msg_id = data.get("last_msg_id")
    if last_msg_id:
        with suppress(TelegramBadRequest):
            await bot.delete_message(chat_id=chat_id, message_id=last_msg_id)
        await state.update_data(last_msg_id=None)

async def delete_messages_list(state: FSMContext, bot: Bot, chat_id: int, key: str):
    """Видаляє список повідомлень з безпечною затримкою."""
    data = await state.get_data()
    msg_ids = data.get(key, [])
    
    if msg_ids:
        for mid in msg_ids:
            with suppress(TelegramBadRequest):
                await bot.delete_message(chat_id=chat_id, message_id=mid)
                await asyncio.sleep(0.05) 
        await state.update_data({key: []})

async def update_or_send_msg(bot: Bot, chat_id: int, state: FSMContext, text: str, kb=None):
    """
    Розумна функція відправки:
    1. Пробує редагувати старе.
    2. Якщо помилка або старого немає -> видаляє старе (щоб не дублювалось) і шле нове.
    """
    data = await state.get_data()
    last_msg_id = data.get("last_msg_id")

    # Спроба редагування
    if last_msg_id:
        try:
            await bot.edit_message_text(
                text=text, 
                chat_id=chat_id, 
                message_id=last_msg_id, 
                reply_markup=kb, 
                parse_mode="HTML"
            )
            return # Успіх
        except Exception:
            # Якщо редагувати не вийшло (наприклад, повідомлення застаріло або текст той самий)
            # Ми пробуємо видалити старе, щоб надіслати нове
            with suppress(TelegramBadRequest):
                await bot.delete_message(chat_id=chat_id, message_id=last_msg_id)

    # Відправка нового
    msg = await bot.send_message(chat_id=chat_id, text=text, reply_markup=kb, parse_mode="HTML")
    await state.update_data(last_msg_id=msg.message_id)

async def send_new_clean_msg(message: types.Message, state: FSMContext, text: str, kb=None):
    """Для Reply-клавіатур: видаляє старе і шле нове."""
    await delete_prev_msg(state, message.bot, message.chat.id)
    msg = await message.answer(text, reply_markup=kb, parse_mode="HTML")
    await state.update_data(last_msg_id=msg.message_id)

# ==========================================
# 🌍 ПОШУК МІСТ
# ==========================================

def get_city_suggestion(raw_input: str) -> str | None:
    if not raw_input: return None
    known_cities = get_all_cities_names()
    if not known_cities: return None
    best_match = process.extractOne(raw_input, known_cities)
    if best_match and best_match[1] >= 75:
        return best_match[0]
    return None

def _geocode_sync(text: str):
    try:
        return geolocator.geocode(text, language="uk")
    except Exception as e:
        print(f"⚠️ Geopy Error: {e}")
        return None

async def validate_city_real(city_name: str) -> str | None:
    clean_query = re.sub(r'[^\w\s-]', '', city_name).strip()
    try:
        location = await asyncio.to_thread(_geocode_sync, f"{clean_query}, Ukraine")
        if location: 
            return location.address.split(',')[0]
    except Exception:
        return None 
    return None
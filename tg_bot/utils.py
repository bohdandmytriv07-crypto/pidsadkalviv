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

# 👇 Ініціалізація пошуку в інтернеті (User-Agent обов'язковий, щоб не забанили)
geolocator = Nominatim(user_agent="ua_ride_bot_pidsadka")


# ==========================================
# 🧠 РОЗУМНИЙ ПОШУК (БАЗА + ІНТЕРНЕТ)
# ==========================================

def get_city_suggestion(raw_input: str) -> str | None:
    """
    1. Бере всі міста, які ми ВЖЕ знаємо (з бази).
    2. Шукає схоже (наприклад, юзер ввів 'льві', а в базі є 'Львів').
    """
    if not raw_input: return None
    
    # Отримуємо список міст, які вже збережені в базі даних
    known_cities = get_all_cities_names()
    
    if not known_cities:
        return None

    # Шукаємо найкращий збіг (поріг схожості 75%)
    # extractOne повертає кортеж: ('Львів', 90)
    best_match = process.extractOne(raw_input, known_cities)
    
    if best_match and best_match[1] >= 75:
        return best_match[0] # Повертаємо правильну назву з бази
            
    return None


def validate_city_real(city_name: str) -> str | None:
    """
    Якщо міста немає в базі, перевіряємо його існування через ІНТЕРНЕТ.
    """
    try:
        # Шукаємо тільки в межах України ('uk' - українська мова результату)
        location = geolocator.geocode(f"{city_name}, Ukraine", language="uk")
        
        if location:
            # location.address може бути довгим: "Львів, Львівська громада, ..."
            # Ми беремо тільки першу частину до коми
            real_name = location.address.split(',')[0]
            return real_name
            
    except Exception as e:
        print(f"⚠️ Помилка геокодера: {e}")
        return None 
        
    return None


def is_valid_city(text: str) -> bool:
    """
    Базова перевірка, щоб не шукати в інтернеті набір цифр або матюки.
    """
    if not text or len(text) < 2 or len(text) > 50:
        return False
    # Якщо в тексті є цифри - це не місто
    if any(char.isdigit() for char in text):
        return False
    return True


# ==========================================
# 📲 ІНТЕРФЕЙС ТА ОЧИЩЕННЯ
# ==========================================

async def clean_user_input(message: types.Message):
    """Видаляє повідомлення користувача."""
    with suppress(TelegramBadRequest):
        await message.delete()

async def delete_prev_msg(state: FSMContext, bot: Bot, chat_id: int):
    """Видаляє попереднє повідомлення бота."""
    data = await state.get_data()
    last_msg_id = data.get("last_msg_id")
    if last_msg_id:
        with suppress(TelegramBadRequest):
            await bot.delete_message(chat_id=chat_id, message_id=last_msg_id)
        await state.update_data(last_msg_id=None)

async def send_new_clean_msg(message: types.Message, state: FSMContext, text: str, kb=None):
    """Видаляє старе -> Шле нове."""
    await delete_prev_msg(state, message.bot, message.chat.id)
    msg = await message.answer(text, reply_markup=kb, parse_mode="HTML")
    await state.update_data(last_msg_id=msg.message_id)

async def update_or_send_msg(bot: Bot, chat_id: int, state: FSMContext, text: str, kb=None):
    """
    Спробує відредагувати. Якщо не вийде - видалить і надішле нове.
    Це робить бота плавним і приємним.
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
            return
        except TelegramBadRequest:
            pass # Повідомлення старе або з фото, редагувати не можна
            
    await delete_prev_msg(state, bot, chat_id)
    msg = await bot.send_message(chat_id=chat_id, text=text, reply_markup=kb, parse_mode="HTML")
    await state.update_data(last_msg_id=msg.message_id)
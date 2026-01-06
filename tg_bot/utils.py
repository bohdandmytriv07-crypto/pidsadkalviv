import re
from contextlib import suppress
from aiogram import types, Bot
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

# 👇 Бібліотеки для пошуку
from thefuzz import process
from geopy.geocoders import Nominatim
from database import get_all_cities_names

# 👇 Ініціалізація геокодера (User-Agent обов'язковий!)
geolocator = Nominatim(user_agent="ua_ride_bot_v1")

# ==========================================
# 🧹 ОЧИЩЕННЯ ТА ВАЛІДАЦІЯ
# ==========================================

async def clean_user_input(message: types.Message):
    """
    Безпечно видаляє повідомлення, яке написав користувач.
    Використовується, щоб текстові команди або відповіді не засмічували чат.
    """
    with suppress(TelegramBadRequest):
        await message.delete()


def get_city_suggestion(text: str, threshold: int = 75) -> str | None:
    """
    Шукає схоже місто у ЛОКАЛЬНІЙ БАЗІ.
    Використовується для швидкого пошуку без запитів до інтернету.
    """
    if not text: return None
    
    # 1. Беремо свіжий список з бази
    cities = get_all_cities_names()
    if not cities: return None

    # 2. Шукаємо найкращий збіг ('Львів', 90)
    best_match = process.extractOne(text, cities)
    
    if best_match and best_match[1] >= threshold:
        return best_match[0] # Повертаємо назву з бази
            
    return None


def validate_city_real(city_name: str) -> str | None:
    """
    Перевіряє місто через ІНТЕРНЕТ (OpenStreetMap).
    Використовується, якщо міста немає в нашій базі.
    """
    try:
        # Шукаємо тільки в Україні
        location = geolocator.geocode(f"{city_name}, Ukraine", language="uk")
        
        if location:
            # location.address повертає повну адресу, беремо тільки першу частину (назву міста)
            # Наприклад: "Київ, Україна" -> "Київ"
            return location.address.split(',')[0]
            
    except Exception:
        return None # Помилка з'єднання або інше
        
    return None


def is_valid_city(text: str) -> bool:
    """
    Базова перевірка на спецсимволи (RegEx).
    Дозволено: Літери, цифри, дефіс, пробіл, апостроф.
    """
    if not text or len(text) < 2 or len(text) > 50:
        return False
    
    pattern = r"^[A-Za-zА-Яа-яЇїІіЄєҐґ0-9\s\-\']+$"
    return bool(re.match(pattern, text))


# ==========================================
# 📲 КЕРУВАННЯ ІНТЕРФЕЙСОМ (ПОВІДОМЛЕННЯМИ)
# ==========================================

async def update_or_send_msg(
    bot: Bot, 
    chat_id: int, 
    state: FSMContext, 
    text: str, 
    markup: types.InlineKeyboardMarkup | None = None
):
    """
    Головна функція для 'плинного' інтерфейсу (Flow).
    1. Намагається ВІДРЕДАГУВАТИ останнє повідомлення бота.
    2. Якщо це неможливо — ВИДАЛЯЄ старе і надсилає НОВЕ.
    """
    data = await state.get_data()
    last_msg_id = data.get("last_msg_id")

    if last_msg_id:
        try:
            # Спробуємо відредагувати
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=last_msg_id,
                text=text,
                reply_markup=markup,
                parse_mode="HTML"
            )
            return # Успішно відредагували, виходимо
        except Exception:
            # Якщо редагування не вдалося (наприклад, змінився тип повідомлення або воно старе)
            # Спробуємо його видалити, щоб не висіло в чаті
            with suppress(TelegramBadRequest):
                await bot.delete_message(chat_id=chat_id, message_id=last_msg_id)
    
    # Надсилаємо нове повідомлення
    msg = await bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=markup,
        parse_mode="HTML"
    )
    # Зберігаємо ID нового повідомлення
    await state.update_data(last_msg_id=msg.message_id)


async def renew_interface(bot: Bot, chat_id: int, state: FSMContext, text: str, markup: types.InlineKeyboardMarkup | None = None):
    """
    Функція для ПОВНОГО оновлення меню (наприклад, при /start).
    Примусово видаляє старі повідомлення і шле нове.
    """
    data = await state.get_data()
    
    ids_to_clean = [data.get("last_msg_id"), data.get("last_interface_id")]
    
    for mid in ids_to_clean:
        if mid:
            with suppress(TelegramBadRequest):
                await bot.delete_message(chat_id=chat_id, message_id=mid)

    new_msg = await bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=markup,
        parse_mode="HTML"
    )

    await state.update_data(last_msg_id=new_msg.message_id, last_interface_id=new_msg.message_id)


async def delete_prev_msg(state: FSMContext, bot: Bot, chat_id: int):
    """Видаляє останнє повідомлення бота, збережене в стані."""
    data = await state.get_data()
    last_msg_id = data.get("last_msg_id")
    
    if last_msg_id:
        with suppress(TelegramBadRequest):
            await bot.delete_message(chat_id=chat_id, message_id=last_msg_id)
        await state.update_data(last_msg_id=None)


async def send_new_clean_msg(message: types.Message, state: FSMContext, text: str, markup: types.InlineKeyboardMarkup | None = None):
    """Примусово видаляє старе -> Шле нове (коли не можна редагувати)."""
    await delete_prev_msg(state, message.bot, message.chat.id)
    
    msg = await message.answer(text, reply_markup=markup, parse_mode="HTML")
    await state.update_data(last_msg_id=msg.message_id)


async def update_interface(message: types.Message, text: str, markup: types.InlineKeyboardMarkup | None = None):
    """Обгортка для callback-ів: редагує повідомлення, на якому натиснули кнопку."""
    try:
        await message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    except Exception:
        await message.answer(text, reply_markup=markup, parse_mode="HTML")
import re
from contextlib import suppress
from aiogram import types, Bot
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

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


def is_valid_city(text: str) -> bool:
    """
    Перевіряє, чи є текст валідною назвою міста.
    Дозволено: Літери, ЦИФРИ, дефіс, пробіл, апостроф.
    Заборонено: Спецсимволи (@, #, /, тощо).
    Мін. довжина: 2 символи.
    """
    if not text or len(text) < 2 or len(text) > 50:
        return False
    
    # Дозволяємо літери, цифри, пробіли, дефіс, апостроф
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
    2. Якщо це неможливо (воно старе або видалене) — надсилає НОВЕ.
    3. Завжди зберігає ID актуального повідомлення в FSM.
    """
    data = await state.get_data()
    last_msg_id = data.get("last_msg_id")

    if last_msg_id:
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=last_msg_id,
                text=text,
                reply_markup=markup,
                parse_mode="HTML"
            )
            return # Успішно відредагували, виходимо
        except Exception:
            # Повідомлення не знайдено або його не можна редагувати
            pass
    
    # Якщо редагування не вдалося — шлемо нове
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
    1. Примусово ВИДАЛЯЄ старе меню (якщо його ID збережено).
    2. Надсилає НОВЕ повідомлення.
    3. Зберігає його ID як 'last_msg_id'.
    """
    data = await state.get_data()
    
    # Спробуємо видалити повідомлення, збережені під різними ключами
    ids_to_clean = [data.get("last_msg_id"), data.get("last_interface_id")]
    
    for mid in ids_to_clean:
        if mid:
            with suppress(TelegramBadRequest):
                await bot.delete_message(chat_id=chat_id, message_id=mid)

    # Надсилаємо абсолютно нове меню
    new_msg = await bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=markup,
        parse_mode="HTML"
    )

    # Зберігаємо ID і як msg, і як interface, щоб точно знайти його наступного разу
    await state.update_data(last_msg_id=new_msg.message_id, last_interface_id=new_msg.message_id)


async def delete_prev_msg(state: FSMContext, bot: Bot, chat_id: int):
    """
    Допоміжна функція: просто видаляє останнє повідомлення бота, якщо воно є.
    """
    data = await state.get_data()
    last_msg_id = data.get("last_msg_id")
    
    if last_msg_id:
        with suppress(TelegramBadRequest):
            await bot.delete_message(chat_id=chat_id, message_id=last_msg_id)
        await state.update_data(last_msg_id=None)


async def send_new_clean_msg(message: types.Message, state: FSMContext, text: str, markup: types.InlineKeyboardMarkup | None = None):
    """
    Примусово видаляє старе -> Шле нове.
    Використовується там, де редагування технічно неможливе (наприклад, зміна типу контенту).
    """
    await delete_prev_msg(state, message.bot, message.chat.id)
    
    msg = await message.answer(text, reply_markup=markup, parse_mode="HTML")
    await state.update_data(last_msg_id=msg.message_id)


async def update_interface(message: types.Message, text: str, markup: types.InlineKeyboardMarkup | None = None):
    """
    Проста обгортка для callback-ів.
    Намагається редагувати те повідомлення, на якому натиснули кнопку.
    """
    try:
        await message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    except Exception:
        await message.answer(text, reply_markup=markup, parse_mode="HTML")
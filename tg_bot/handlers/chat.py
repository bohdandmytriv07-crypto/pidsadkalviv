import logging
from contextlib import suppress
from aiogram import Router, F, types, Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

# Імпорти з ваших файлів
from database import (
    set_active_chat, get_active_chat_partner, delete_active_chat,
    save_chat_msg, get_and_clear_chat_msgs, get_user, save_user
)
from keyboards import kb_main_role

router = Router()

# ==========================================
# 💬 ПОЧАТОК ЧАТУ
# ==========================================

@router.callback_query(F.data.startswith("chat_start_"))
async def start_chat_handler(call: types.CallbackQuery, bot: Bot):
    """
    Ініціалізація чату: створення запису в БД, відправка привітання.
    """
    my_id = call.from_user.id
    try:
        partner_id = int(call.data.split("_")[2])
    except (ValueError, IndexError):
        await call.answer("Помилка ID", show_alert=True)
        return
    
    # 0. Якщо мене немає в базі (після очищення), створимо
    if not get_user(my_id):
        save_user(my_id, call.from_user.full_name, "-")

    # 1. Записуємо в базу, що я говорю з цим партнером
    set_active_chat(my_id, partner_id)

    # Отримуємо ім'я партнера для краси
    partner_user = get_user(partner_id)
    partner_name = partner_user['name'] if partner_user else "Користувач"

    # 2. Видаляємо старі повідомлення (щоб не було сміття)
    with suppress(TelegramBadRequest):
        await call.message.delete()

    # 3. Створюємо повідомлення "Чат відкрито"
    kb_chat = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔴 Завершити чат", callback_data="chat_stop")]
    ])
    
    msg = await call.message.answer(
        f"💬 <b>Чат з {partner_name} відкрито!</b>\n"
        f"Пишіть повідомлення, і я передам їх.\n"
        f"👇 Натисніть кнопку нижче, щоб вийти.",
        reply_markup=kb_chat,
        parse_mode="HTML"
    )
    
    # 4. Зберігаємо ID цього повідомлення (щоб потім видалити)
    save_chat_msg(my_id, msg.message_id)
    await call.answer()


# ==========================================
# 📨 ПЕРЕСИЛКА ПОВІДОМЛЕНЬ
# ==========================================

@router.message()
async def chat_message_handler(message: types.Message, bot: Bot):
    """
    Перехоплює всі текстові повідомлення.
    Якщо є активний чат — пересилає партнеру.
    """
    my_id = message.from_user.id
    
    # Перевіряємо, чи є у користувача активний чат
    partner_id = get_active_chat_partner(my_id)
    
    # Якщо чату немає — ігноруємо (повідомлення піде далі в інші хендлери)
    if not partner_id:
        return

    # --- ПЕРЕСИЛКА ---
    try:
        # Кнопка для партнера, щоб він теж міг відповісти
        kb_reply = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="↩️ Відповісти", callback_data=f"chat_start_{my_id}")]
        ])
        
        # Відправляємо повідомлення партнеру
        # Використовуємо copy_to, щоб підтримувати фото, стікери тощо
        sent_msg = await message.copy_to(
            chat_id=partner_id,
            reply_markup=kb_reply
        )
        
        # Зберігаємо ID повідомлення У ПАРТНЕРА (щоб можна було очистити його чат теж)
        save_chat_msg(partner_id, sent_msg.message_id)
        
    except Exception as e:
        logging.warning(f"Помилка доставки повідомлення: {e}")
        await message.answer("❌ Не вдалося доставити повідомлення. Користувач заблокував бота.")


# ==========================================
# 🛑 ЗАВЕРШЕННЯ ЧАТУ (З ОЧИЩЕННЯМ)
# ==========================================

@router.callback_query(F.data == "chat_stop")
async def stop_chat_handler(call: types.CallbackQuery, bot: Bot):
    """
    Завершує чат, видаляє всі системні повідомлення і повертає меню.
    """
    user_id = call.from_user.id
    
    # 1. Видаляємо запис про активний чат
    delete_active_chat(user_id)
    
    # 2. --- ОЧИЩЕННЯ ПОВІДОМЛЕНЬ БОТА ---
    msg_ids = get_and_clear_chat_msgs(user_id)
    
    for mid in msg_ids:
        with suppress(TelegramBadRequest):
            await bot.delete_message(chat_id=user_id, message_id=mid)
            
    # Також видаляємо кнопку "Завершити"
    with suppress(TelegramBadRequest):
        await call.message.delete()

    # 3. Сповіщення про завершення і повернення в меню
    await call.message.answer(
        "✅ <b>Чат завершено.</b>",
        reply_markup=kb_main_role(), 
        parse_mode="HTML"
    )
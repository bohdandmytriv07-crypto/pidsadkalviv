import asyncio
from contextlib import suppress
from aiogram import Router, F, types, Bot
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.context import FSMContext

from utils import delete_messages_list

from database import (
    set_active_chat, get_active_chat_partner, delete_active_chat, get_user,
    save_chat_msg, get_and_clear_chat_msgs, 
    save_message_to_history, get_chat_history_text
)
from keyboards import kb_menu

router = Router()

EXIT_TEXT = "❌ Завершити діалог"

# ==========================================
# ⌨️ КЛАВІАТУРИ
# ==========================================

def kb_chat_actions(partner_username=None):
    buttons = [
        [InlineKeyboardButton(text="📍 Я на місці", callback_data="tpl_here"),
         InlineKeyboardButton(text="⏱ Запізнююсь 5 хв", callback_data="tpl_late")]
    ]
    if partner_username:
        buttons.append([InlineKeyboardButton(text="✈️ Написати в ПП", url=f"https://t.me/{partner_username}")])
    buttons.append([InlineKeyboardButton(text="❌ Завершити діалог", callback_data="chat_leave")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def kb_reply(user_id):
    """
    Кнопки під вхідним повідомленням.
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Відповісти", callback_data=f"chat_reply_{user_id}")],
        [InlineKeyboardButton(text="👌 Гляну пізніше", callback_data="hide_msg")]
    ])

def kb_chat_bottom():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=EXIT_TEXT)],
        [KeyboardButton(text="📍 Надіслати геопозицію", request_location=True), KeyboardButton(text="📞 Надіслати мій номер", request_contact=True)]
    ], resize_keyboard=True)

# ==========================================
# 🙈 ОБРОБКА КНОПКИ "СХОВАТИ"
# ==========================================

@router.callback_query(F.data == "hide_msg")
async def hide_message_handler(call: types.CallbackQuery):
    with suppress(TelegramBadRequest):
        await call.message.delete()

# ==========================================
# 💬 СТАРТ ЧАТУ
# ==========================================

@router.callback_query(F.data.startswith("chat_start_") | F.data.startswith("chat_reply_"))
async def start_chat_handler(call: types.CallbackQuery, bot: Bot, state: FSMContext):
    target_user_id = int(call.data.split("_")[2])
    my_id = call.from_user.id

    if target_user_id == my_id:
        await call.answer("Не можна писати самому собі!", show_alert=True)
        return

    # 🔥 ЛОГІКА ЦИТУВАННЯ: Зберігаємо текст ДО видалення повідомлення
    # 🔥 ЛОГІКА ЦИТУВАННЯ: Зберігаємо текст ДО видалення повідомлення
    reply_context = None
    if call.data.startswith("chat_reply_"):
        # Пробуємо дістати текст
        raw_text = call.message.text or call.message.caption
        
        # Якщо тексту немає, перевіряємо інші типи
        if not raw_text:
            if call.message.voice: raw_text = "🎤 [Голосове повідомлення]"
            elif call.message.video_note: raw_text = "⏺ [Відеоповідомлення]"
            elif call.message.sticker: raw_text = "👾 [Стікер]"
            elif call.message.photo: raw_text = "🖼 [Фото]"
            elif call.message.video: raw_text = "📹 [Відео]"
            elif call.message.document: raw_text = "📁 [Файл]"
            elif call.message.location: raw_text = "📍 [Геолокація]"
            elif call.message.contact: 
                 raw_text = f"👤 Контакт: {call.message.contact.first_name}"
            else: raw_text = "📨 [Повідомлення]"

        # Обробка цитати
        if "\n" in raw_text and not raw_text.startswith("["): 
             # Якщо це старе текстове повідомлення формату "Name:\nText", пробуємо взяти тільки текст
             try: reply_context = raw_text.split("\n", 1)[1]
             except IndexError: reply_context = raw_text
        else:
             reply_context = raw_text

    target_user = get_user(target_user_id)
    if not target_user:
        await call.answer("Користувача не знайдено.", show_alert=True)
        return

    # Чистка інтерфейсу
    chat_id = call.message.chat.id
    await delete_messages_list(state, bot, chat_id, "trip_msg_ids")     
    await delete_messages_list(state, bot, chat_id, "booking_msg_ids")  
    await delete_messages_list(state, bot, chat_id, "search_msg_ids")   

    # Видаляємо старе сповіщення
    with suppress(TelegramBadRequest): await call.message.delete()

    set_active_chat(my_id, target_user_id)

    # 1. Історія (Останні повідомлення)
    history = get_chat_history_text(my_id, target_user_id)
    if history:
        hist_msg = await call.message.answer(history, parse_mode="HTML")
        save_chat_msg(my_id, hist_msg.message_id)

    # 2. 🔥 ВІДОБРАЖЕННЯ ЦИТАТИ (На що відповідаємо)
    if reply_context:
        # Обрізаємо, якщо дуже довге
        if len(reply_context) > 100: reply_context = reply_context[:100] + "..."
        
        quote_msg = await call.message.answer(
            f"⤵️ <b>Ви відповідаєте на:</b>\n<i>{reply_context}</i>", 
            parse_mode="HTML"
        )
        save_chat_msg(my_id, quote_msg.message_id)

    # 3. Інфо про співрозмовника
    username = target_user.get('username')
    clean_username = username.replace("@", "") if username else None
    
    t_name = target_user['name'] or "Користувач"
    t_phone = target_user['phone'] if target_user['phone'] != "-" else "<i>(номер приховано)</i>"
    
    intro_text = (
        f"💬 <b>Діалог з {t_name}</b>\n"
        f"📞 {t_phone}\n"
        f"⚠️ <i>Не надсилайте передоплату на карту!</i>"
    )

    # 4. Меню чату
    msg = await call.message.answer(intro_text, reply_markup=kb_chat_actions(clean_username), parse_mode="HTML")
    save_chat_msg(my_id, msg.message_id)
    
    kb_msg = await call.message.answer("⌨️ Клавіатура відкрита:", reply_markup=kb_chat_bottom())
    save_chat_msg(my_id, kb_msg.message_id)
    
    await call.answer()

# ==========================================
# ⚡ ШАБЛОНИ
# ==========================================

@router.callback_query(F.data.startswith("tpl_"))
async def quick_reply_handler(call: types.CallbackQuery, bot: Bot):
    action = call.data.split("_")[1]
    user_id = call.from_user.id
    partner_id = get_active_chat_partner(user_id)
    if not partner_id: return

    tpl_map = {"here": "📍 Я вже на місці!", "late": "⏱ Запізнююсь на 5 хв."}
    await _relay_message(bot, user_id, partner_id, text=tpl_map.get(action, "..."))
    await call.answer()

# ==========================================
# 🛑 ОЧИСТКА ТА ВИХІД
# ==========================================

async def _stop_chat_logic(user_id: int, bot: Bot, state: FSMContext, trigger_msg: types.Message = None):
    delete_active_chat(user_id)
    
    rm_msg = await bot.send_message(user_id, "🔄 Завершення...", reply_markup=ReplyKeyboardRemove())
    
    msg_ids = get_and_clear_chat_msgs(user_id)
    msg_ids.append(rm_msg.message_id)
    if trigger_msg: msg_ids.append(trigger_msg.message_id)

    data = await state.get_data()
    if data.get("last_msg_id"):
        msg_ids.append(data["last_msg_id"])

    for mid in msg_ids:
        with suppress(TelegramBadRequest):
            await bot.delete_message(chat_id=user_id, message_id=mid)
            await asyncio.sleep(0.05)

    role = data.get("role", "passenger")
    new_menu = await bot.send_message(user_id, f"✅ <b>Діалог завершено.</b>", reply_markup=kb_menu(role), parse_mode="HTML")
    await state.update_data(last_msg_id=new_menu.message_id)

@router.callback_query(F.data == "chat_leave")
async def leave_chat_inline(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    await _stop_chat_logic(call.from_user.id, bot, state, call.message)

@router.message(F.text == EXIT_TEXT)
async def leave_chat_text(message: types.Message, state: FSMContext, bot: Bot):
    await _stop_chat_logic(message.from_user.id, bot, state, message)

# ==========================================
# 📨 ПЕРЕСИЛАННЯ
# ==========================================

async def _relay_message(bot: Bot, sender_id: int, receiver_id: int, text=None, original_msg: types.Message=None):
    sender = get_user(sender_id)
    sender_name = sender['name'] if (sender and sender['name']) else "Користувач"
    
    if original_msg:
        save_chat_msg(sender_id, original_msg.message_id)

    # 🔥 ВИЗНАЧАЄМО ТИП КОНТЕНТУ ДЛЯ ІСТОРІЇ
    history_text = text
    if not history_text and original_msg:
        if original_msg.photo: history_text = "[Фото]"
        elif original_msg.voice: history_text = "[Голосове]"
        elif original_msg.sticker: history_text = "[Стікер]"
        elif original_msg.location: history_text = "[Мапа]"
        elif original_msg.contact: history_text = "[Контакт]"
        else: history_text = "[Вкладення]"

    try:
        sent_msg = None
        if text:
            # Текстове повідомлення
            sent_msg = await bot.send_message(receiver_id, f"👤 <b>{sender_name}:</b>\n{text}", reply_markup=kb_reply(sender_id), parse_mode="HTML")
        elif original_msg:
            # Медіа (фото, стікер тощо) - використовуємо copy_to
            sent_msg = await original_msg.copy_to(receiver_id, caption=f"👤 <b>{sender_name}</b>", reply_markup=kb_reply(sender_id), parse_mode="HTML")
        
        # Зберігаємо в історію правильний опис
        if history_text:
            save_message_to_history(sender_id, receiver_id, history_text)
        
        if sent_msg: save_chat_msg(receiver_id, sent_msg.message_id)

        ack_text = f"✅ Ви: {history_text}" 
        ack = await bot.send_message(sender_id, ack_text)
        save_chat_msg(sender_id, ack.message_id)

    except TelegramForbiddenError:
        await bot.send_message(sender_id, "❌ Користувач заблокував бота.")
        delete_active_chat(sender_id)

# 📂 chat.py

@router.message(F.text & (F.text != EXIT_TEXT))
@router.message(F.photo | F.voice | F.location | F.contact) 
async def chat_relay_handler(message: types.Message, bot: Bot):
    partner_id = get_active_chat_partner(message.from_user.id)
    
    # Якщо чату немає, ігноруємо
    if not partner_id: return 
   
    # Валідація довжини
    if message.text and len(message.text) > 1000:
        # Тут можна не видаляти, а просто попередити
        await message.answer("⚠️ <b>Повідомлення занадто довге!</b>\nМаксимум 1000 символів.")
        return

    # 🔥 ЗМІНА: Спочатку пробуємо переслати
    try:
        if message.text: 
            await _relay_message(bot, message.from_user.id, partner_id, text=message.text, original_msg=message)
        else: 
            await _relay_message(bot, message.from_user.id, partner_id, text=None, original_msg=message)
            
        
        with suppress(TelegramBadRequest):
            await message.delete()
            
    except Exception as e:
        print(f"Chat Relay Error: {e}")
        await message.answer("❌ <b>Помилка доставки!</b> Спробуйте ще раз.")
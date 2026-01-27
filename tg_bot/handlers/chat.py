import asyncio
from contextlib import suppress
from aiogram import Router, F, types, Bot
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.context import FSMContext

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
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↩️ Відповісти", callback_data=f"chat_reply_{user_id}")]])

def kb_chat_bottom():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=EXIT_TEXT)],
        [KeyboardButton(text="📍 Надіслати геопозицію", request_location=True), KeyboardButton(text="📞 Надіслати мій номер", request_contact=True)]
    ], resize_keyboard=True)

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

    target_user = get_user(target_user_id)
    if not target_user:
        await call.answer("Користувача не знайдено.", show_alert=True)
        return

    set_active_chat(my_id, target_user_id)
    with suppress(TelegramBadRequest): await call.message.delete()

    # 1. Історія
    history = get_chat_history_text(my_id, target_user_id)
    if history:
        hist_msg = await call.message.answer(history, parse_mode="HTML")
        save_chat_msg(my_id, hist_msg.message_id) # Зберігаємо для видалення

    # 2. Інфо
    username = target_user.get('username')
    clean_username = username.replace("@", "") if username else None
    phone_info = f"📞 <code>{target_user['phone']}</code>" if target_user['phone'] != "-" else "<i>(номер приховано)</i>"
    
    intro_text = (
        f"💬 <b>Діалог з {target_user['name']}</b>\n"
        f"{phone_info}\n"
        f"⚠️ <i>Не надсилайте передоплату на карту!</i>"
    )

    # 3. Інтерфейс
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
    
    # Видаляємо нижню клавіатуру
    rm_msg = await bot.send_message(user_id, "🔄 Завершення...", reply_markup=ReplyKeyboardRemove())
    
    # 🔥 ЗБИРАЄМО ВСІ ID ДЛЯ ВИДАЛЕННЯ
    msg_ids = get_and_clear_chat_msgs(user_id)
    msg_ids.append(rm_msg.message_id)
    if trigger_msg: msg_ids.append(trigger_msg.message_id)

    # Видаляємо пачкою
    for mid in msg_ids:
        with suppress(TelegramBadRequest):
            await bot.delete_message(chat_id=user_id, message_id=mid)

    # Повертаємо меню
    data = await state.get_data()
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
    sender_name = sender['name'] if sender else "Співрозмовник"
    
    # 🔥 Зберігаємо ID вхідного повідомлення користувача (щоб потім видалити)
    if original_msg:
        save_chat_msg(sender_id, original_msg.message_id)

    try:
        sent_msg = None
        if text:
            sent_msg = await bot.send_message(receiver_id, f"👤 <b>{sender_name}:</b>\n{text}", reply_markup=kb_reply(sender_id), parse_mode="HTML")
            save_message_to_history(sender_id, receiver_id, text)
        elif original_msg:
            if original_msg.contact:
                sent_msg = await bot.send_contact(receiver_id, original_msg.contact.phone_number, original_msg.contact.first_name, reply_markup=kb_reply(sender_id))
            else:
                sent_msg = await original_msg.copy_to(receiver_id, caption=f"👤 <b>{sender_name}</b> надіслав вкладення.", reply_markup=kb_reply(sender_id), parse_mode="HTML")
        
        # Зберігаємо ID повідомлення у партнера (для його очистки)
        if sent_msg: save_chat_msg(receiver_id, sent_msg.message_id)

        # 🔥 Зберігаємо підтвердження у себе
        ack_text = f"✅ Ви: {text}" if text else "✅ Ви надіслали файл."
        ack = await bot.send_message(sender_id, ack_text)
        save_chat_msg(sender_id, ack.message_id)

    except TelegramForbiddenError:
        await bot.send_message(sender_id, "❌ Користувач заблокував бота.")
        delete_active_chat(sender_id)

@router.message(F.text & (F.text != EXIT_TEXT))
@router.message(F.photo | F.voice | F.location | F.contact) 
async def chat_relay_handler(message: types.Message, bot: Bot):
    partner_id = get_active_chat_partner(message.from_user.id)
    if partner_id:
        if message.text: await _relay_message(bot, message.from_user.id, partner_id, text=message.text, original_msg=message)
        else: await _relay_message(bot, message.from_user.id, partner_id, text=None, original_msg=message)
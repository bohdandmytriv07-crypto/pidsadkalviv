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

# Текст кнопки виходу (має бути однаковий всюди)
EXIT_TEXT = "❌ Завершити діалог"

def kb_chat_actions():
    """Inline-кнопки під повідомленнями."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📍 Я на місці", callback_data="tpl_here"),
            InlineKeyboardButton(text="⏱ Запізнююсь 5 хв", callback_data="tpl_late")
        ],
        [InlineKeyboardButton(text=EXIT_TEXT, callback_data="chat_leave")]
    ])

def kb_reply(user_id):
    """Кнопка 'Відповісти'."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Відповісти", callback_data=f"chat_reply_{user_id}")]
    ])

def kb_chat_bottom():
    """Нижня клавіатура для зручності."""
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=EXIT_TEXT)],
        [KeyboardButton(text="📍 Надіслати геопозицію", request_location=True)]
    ], resize_keyboard=True)


# --- 1. СТАРТ ЧАТУ ---
@router.callback_query(F.data.startswith("chat_start_") | F.data.startswith("chat_reply_"))
async def start_chat_handler(call: types.CallbackQuery, bot: Bot, state: FSMContext):
    target_user_id = int(call.data.split("_")[2])
    my_id = call.from_user.id

    if target_user_id == my_id:
        await call.answer("Це ви!", show_alert=True)
        return

    target_user = get_user(target_user_id)
    if not target_user:
        await call.answer("Користувача не знайдено.", show_alert=True)
        return

    set_active_chat(my_id, target_user_id)
    
    with suppress(TelegramBadRequest):
        await call.message.delete()

    history = get_chat_history_text(my_id, target_user_id)
    if history:
        hist_msg = await call.message.answer(history, parse_mode="HTML")
        save_chat_msg(my_id, hist_msg.message_id)

    phone_info = f"📞 <code>{target_user['phone']}</code>" if target_user['phone'] != "-" else ""

    # 🔥 Відправляємо повідомлення і додаємо НИЖНЮ КЛАВІАТУРУ
    msg = await call.message.answer(
        f"💬 <b>Діалог з {target_user['name']}</b>\n{phone_info}\n"
        f"<i>Ви можете надсилати текст, фото або локацію.</i>", 
        reply_markup=kb_chat_bottom(), 
        parse_mode="HTML"
    )
    save_chat_msg(my_id, msg.message_id)
    await call.answer()


# --- 2. ШВИДКІ ВІДПОВІДІ ---
@router.callback_query(F.data.startswith("tpl_"))
async def quick_reply_handler(call: types.CallbackQuery, bot: Bot):
    action = call.data.split("_")[1]
    user_id = call.from_user.id
    partner_id = get_active_chat_partner(user_id)
    
    if not partner_id:
        await call.answer("Чат не активний", show_alert=True)
        return

    tpl_map = {
        "here": "📍 Я вже на місці!",
        "late": "⏱ Я трохи запізнююсь, зачекайте будь ласка."
    }
    text_to_send = tpl_map.get(action, "...")

    await bot.send_chat_action(chat_id=partner_id, action="typing")
    await asyncio.sleep(0.5)

    try:
        sent = await bot.send_message(
            partner_id, 
            f"👤 <b>Співрозмовник:</b>\n{text_to_send}", 
            reply_markup=kb_reply(user_id),
            parse_mode="HTML"
        )
        save_message_to_history(user_id, partner_id, text_to_send)
        save_chat_msg(partner_id, sent.message_id)
        
        my_copy = await call.message.answer(f"✅ Ви: {text_to_send}")
        save_chat_msg(user_id, my_copy.message_id)
        
    except Exception:
        await call.answer("Не вдалося надіслати.")

    await call.answer()


# ==========================================
# 🛑 3. ЗАВЕРШЕННЯ (Обробляє і Кнопку, і Текст)
# ==========================================

async def _stop_chat_logic(user_id: int, bot: Bot, state: FSMContext, message_to_reply: types.Message = None):
    """Спільна логіка для виходу."""
    delete_active_chat(user_id)
    
    # 1. Видаляємо нижню клавіатуру
    removing_msg = await bot.send_message(user_id, "🔄 Завершення...", reply_markup=ReplyKeyboardRemove())
    
    # 2. Чистимо історію повідомлень на екрані
    msg_ids = get_and_clear_chat_msgs(user_id)
    msg_ids.append(removing_msg.message_id)
    if message_to_reply:
        msg_ids.append(message_to_reply.message_id)

    for mid in msg_ids:
        with suppress(TelegramBadRequest):
            await bot.delete_message(chat_id=user_id, message_id=mid)

    # 3. Повертаємо меню
    data = await state.get_data()
    role = data.get("role", "passenger")
    
    new_menu = await bot.send_message(
        user_id,
        f"✅ <b>Діалог завершено.</b>\nМеню {role}:", 
        reply_markup=kb_menu(role), 
        parse_mode="HTML"
    )
    await state.update_data(last_msg_id=new_menu.message_id)


# Обробка натискання INLINE кнопки "Завершити"
@router.callback_query(F.data == "chat_leave")
async def leave_chat_inline(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    await _stop_chat_logic(call.from_user.id, bot, state, call.message)

# 🔥 Обробка НАТИСКАННЯ НИЖНЬОЇ КНОПКИ (Текст)
# Цей хендлер стоїть ПЕРЕД пересиланням, тому він перехопить текст
@router.message(F.text == EXIT_TEXT)
async def leave_chat_text(message: types.Message, state: FSMContext, bot: Bot):
    await _stop_chat_logic(message.from_user.id, bot, state, message)


# ==========================================
# 📨 4. ПЕРЕСИЛАННЯ (Relay)
# ==========================================

# 🔥 Фільтр: Текст, який НЕ дорівнює команді виходу
@router.message(F.text & (F.text != EXIT_TEXT))
@router.message(F.photo | F.voice | F.video | F.location | F.sticker) 
async def chat_relay_handler(message: types.Message, bot: Bot):
    user_id = message.from_user.id
    partner_id = get_active_chat_partner(user_id)
    
    # Якщо чату немає - ігноруємо (або можна видаляти повідомлення)
    if not partner_id: 
        return

    save_chat_msg(user_id, message.message_id)
    sender = get_user(user_id)
    sender_name = sender['name'] if sender else "Співрозмовник"

    try:
        action = "upload_photo" if message.photo else "find_location" if message.location else "typing"
        await bot.send_chat_action(chat_id=partner_id, action=action)
        await asyncio.sleep(0.3)

        sent_msg = None
        if message.text:
            msg_text = f"👤 <b>{sender_name}:</b>\n{message.text}"
            sent_msg = await bot.send_message(
                partner_id, msg_text, 
                reply_markup=kb_reply(user_id), 
                parse_mode="HTML"
            )
            save_message_to_history(user_id, partner_id, message.text)
        else:
            sent_msg = await message.copy_to(
                chat_id=partner_id,
                caption=f"👤 <b>{sender_name}</b> надіслав файл.",
                reply_markup=kb_reply(user_id),
                parse_mode="HTML"
            )
            save_message_to_history(user_id, partner_id, "[Медіа-файл]")
        
        if sent_msg:
            save_chat_msg(partner_id, sent_msg.message_id)

    except TelegramForbiddenError:
        await message.answer("❌ Користувач заблокував бота.")
        delete_active_chat(user_id)
    except Exception: pass
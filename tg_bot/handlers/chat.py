import asyncio
from contextlib import suppress
from aiogram import Router, F, types, Bot
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.context import FSMContext

from database import (
    set_active_chat, get_active_chat_partner, delete_active_chat, get_user,
    save_chat_msg, get_and_clear_chat_msgs, 
    save_message_to_history, get_chat_history_text,
    get_trip_details
)
from keyboards import kb_menu

router = Router()

# Текст кнопки виходу
EXIT_TEXT = "❌ Завершити діалог"

# ==========================================
# ⌨️ КЛАВІАТУРИ
# ==========================================

def kb_chat_actions(partner_username=None):
    """Inline-кнопки під повідомленнями."""
    buttons = [
        [
            InlineKeyboardButton(text="📍 Я на місці", callback_data="tpl_here"),
            InlineKeyboardButton(text="⏱ Запізнююсь 5 хв", callback_data="tpl_late")
        ]
    ]
    
    # 🔥 НОВЕ: Кнопка переходу в ПП (якщо є юзернейм)
    if partner_username:
        # t.me/username працює на всіх пристроях
        buttons.append([InlineKeyboardButton(text="✈️ Написати в особисті (ПП)", url=f"https://t.me/{partner_username}")])
    
    buttons.append([InlineKeyboardButton(text=EXIT_TEXT, callback_data="chat_leave")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def kb_reply(user_id):
    """Кнопка 'Відповісти' під повідомленням співрозмовника."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Відповісти", callback_data=f"chat_reply_{user_id}")]
    ])

def kb_chat_bottom():
    """Нижня клавіатура для зручності."""
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
    
    with suppress(TelegramBadRequest):
        await call.message.delete()

    # 1. Показуємо історію (якщо була)
    history = get_chat_history_text(my_id, target_user_id)
    if history:
        hist_msg = await call.message.answer(history, parse_mode="HTML")
        save_chat_msg(my_id, hist_msg.message_id)

    # 2. Формуємо інформацію про співрозмовника
    username = target_user.get('username')
    clean_username = username.replace("@", "") if username else None
    
    phone_info = f"📞 <code>{target_user['phone']}</code>" if target_user['phone'] != "-" else "<i>(номер приховано)</i>"
    rating_str = "" # Тут можна додати рейтинг, якщо хочете

    # 3. 🔥 Попередження про безпеку (Anti-Scam)
    scam_warning = (
        "\n⚠️ <b>Увага!</b> Ніколи не надсилайте передоплату на карту.\n"
        "Розраховуйтесь готівкою або при зустрічі."
    )

    intro_text = (
        f"💬 <b>Діалог з {target_user['name']}</b>\n"
        f"{phone_info}\n"
        f"{scam_warning}\n\n"
        f"<i>Ви можете писати тут або перейти в особисті повідомлення 👇</i>"
    )

    # 🔥 Відправляємо повідомлення з кнопкою ПП
    msg = await call.message.answer(
        intro_text, 
        reply_markup=kb_chat_actions(clean_username), # Передаємо юзернейм для кнопки
        parse_mode="HTML"
    )
    save_chat_msg(my_id, msg.message_id)
    
    # Додатково відкриваємо нижню клавіатуру
    kb_msg = await call.message.answer("⌨️ Клавіатура відкрита:", reply_markup=kb_chat_bottom())
    save_chat_msg(my_id, kb_msg.message_id)
    
    await call.answer()


# ==========================================
# ⚡ ШВИДКІ ВІДПОВІДІ (Templates)
# ==========================================

@router.callback_query(F.data.startswith("tpl_"))
async def quick_reply_handler(call: types.CallbackQuery, bot: Bot):
    action = call.data.split("_")[1]
    user_id = call.from_user.id
    partner_id = get_active_chat_partner(user_id)
    
    if not partner_id:
        await call.answer("Чат не активний", show_alert=True)
        return

    tpl_map = {
        "here": "📍 Я вже на місці! Чекаю.",
        "late": "⏱ Я трохи запізнююсь (5-10 хв), зачекайте будь ласка."
    }
    text_to_send = tpl_map.get(action, "...")

    await _relay_message(bot, user_id, partner_id, text=text_to_send)
    await call.answer()


# ==========================================
# 🛑 ЗАВЕРШЕННЯ
# ==========================================

async def _stop_chat_logic(user_id: int, bot: Bot, state: FSMContext, message_to_reply: types.Message = None):
    delete_active_chat(user_id)
    
    # Видаляємо нижню клавіатуру
    removing_msg = await bot.send_message(user_id, "🔄 Завершення діалогу...", reply_markup=ReplyKeyboardRemove())
    
    # Чистимо екран
    msg_ids = get_and_clear_chat_msgs(user_id)
    msg_ids.append(removing_msg.message_id)
    if message_to_reply: msg_ids.append(message_to_reply.message_id)

    for mid in msg_ids:
        with suppress(TelegramBadRequest):
            await bot.delete_message(chat_id=user_id, message_id=mid)

    # Повертаємо в меню
    data = await state.get_data()
    role = data.get("role", "passenger")
    
    new_menu = await bot.send_message(
        user_id,
        f"✅ <b>Діалог завершено.</b>\nПовертаємось в меню {role}.", 
        reply_markup=kb_menu(role), 
        parse_mode="HTML"
    )
    await state.update_data(last_msg_id=new_menu.message_id)


@router.callback_query(F.data == "chat_leave")
async def leave_chat_inline(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    await _stop_chat_logic(call.from_user.id, bot, state, call.message)

@router.message(F.text == EXIT_TEXT)
async def leave_chat_text(message: types.Message, state: FSMContext, bot: Bot):
    await _stop_chat_logic(message.from_user.id, bot, state, message)


# ==========================================
# 📨 ПЕРЕСИЛАННЯ (Relay Core)
# ==========================================

async def _relay_message(bot: Bot, sender_id: int, receiver_id: int, text=None, original_msg: types.Message=None):
    """Універсальна функція пересилки."""
    sender = get_user(sender_id)
    sender_name = sender['name'] if sender else "Співрозмовник"
    
    # Імітація друку
    action = "typing"
    if original_msg:
        if original_msg.photo: action = "upload_photo"
        elif original_msg.location: action = "find_location"
        elif original_msg.voice: action = "record_voice"
        
    try:
        await bot.send_chat_action(chat_id=receiver_id, action=action)
        await asyncio.sleep(0.3)
        
        sent_msg = None
        
        # 1. Текстове повідомлення (або шаблон)
        if text:
            msg_text = f"👤 <b>{sender_name}:</b>\n{text}"
            sent_msg = await bot.send_message(
                receiver_id, msg_text, 
                reply_markup=kb_reply(sender_id), 
                parse_mode="HTML"
            )
            save_message_to_history(sender_id, receiver_id, text)
            
            # Підтвердження відправнику
            ack = await bot.send_message(sender_id, f"✅ Ви: {text}")
            save_chat_msg(sender_id, ack.message_id)

        # 2. Пересилання медіа/фото/локації
        elif original_msg:
            # Якщо це контакт
            if original_msg.contact:
                sent_msg = await bot.send_contact(
                    receiver_id, 
                    phone_number=original_msg.contact.phone_number, 
                    first_name=original_msg.contact.first_name,
                    reply_markup=kb_reply(sender_id)
                )
                save_message_to_history(sender_id, receiver_id, "[Надіслав контакт]")
            
            # Якщо інше медіа
            else:
                sent_msg = await original_msg.copy_to(
                    chat_id=receiver_id,
                    caption=f"👤 <b>{sender_name}</b> надіслав вкладення.",
                    reply_markup=kb_reply(sender_id),
                    parse_mode="HTML"
                )
                save_message_to_history(sender_id, receiver_id, "[Медіа-файл]")
            
            save_chat_msg(sender_id, original_msg.message_id)

        if sent_msg:
            save_chat_msg(receiver_id, sent_msg.message_id)

    except TelegramForbiddenError:
        await bot.send_message(sender_id, "❌ <b>Помилка:</b> Користувач заблокував бота.", parse_mode="HTML")
        delete_active_chat(sender_id)
    except Exception as e:
        print(f"Chat Relay Error: {e}")


@router.message(F.text & (F.text != EXIT_TEXT))
@router.message(F.photo | F.voice | F.video | F.location | F.sticker | F.contact) 
async def chat_relay_handler(message: types.Message, bot: Bot):
    user_id = message.from_user.id
    partner_id = get_active_chat_partner(user_id)
    
    if not partner_id: 
        return # Ігноруємо повідомлення не в чаті

    if message.text:
        await _relay_message(bot, user_id, partner_id, text=message.text, original_msg=None)
    else:
        await _relay_message(bot, user_id, partner_id, text=None, original_msg=message)
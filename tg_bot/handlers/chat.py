import asyncio
from contextlib import suppress
from aiogram import Router, F, types, Bot
from aiogram.types import ReplyKeyboardRemove
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.context import FSMContext

from database import (
    set_active_chat, get_active_chat_partner, delete_active_chat, get_user,
    save_chat_msg, get_and_clear_chat_msgs, 
    save_message_to_history, get_chat_history_text # 👈 Додані нові функції
)
from keyboards import kb_chat_actions, kb_menu

router = Router()

# ==========================================
# 📞 1. ПОЧАТОК ЧАТУ
# ==========================================

@router.callback_query(F.data.startswith("chat_start_"))
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
    
    # Видаляємо попереднє меню
    try:
        await call.message.delete()
    except: pass

    # 🔥 1. ВІДОБРАЖЕННЯ ІСТОРІЇ (якщо є)
    history = get_chat_history_text(my_id, target_user_id)
    if history:
        hist_msg = await call.message.answer(history, parse_mode="HTML")
        # Зберігаємо ID історії, щоб вона теж зникла при виході (для чистоти)
        save_chat_msg(my_id, hist_msg.message_id)

    # 2. Повідомлення про старт
    msg = await call.message.answer(
        f"💬 <b>Чат з {target_user['name']}</b>\n"
        f"Пишіть повідомлення, я передам.", 
        reply_markup=kb_chat_actions(), 
        parse_mode="HTML"
    )
    
    # Зберігаємо ID системного повідомлення для видалення
    save_chat_msg(my_id, msg.message_id)
    
    set_active_chat(target_user_id, my_id) 


# ==========================================
# 🛑 2. ЗАВЕРШЕННЯ ЧАТУ (Без змін)
# ==========================================

@router.message(F.text == "❌ Завершити чат")
async def end_chat_text_handler(message: types.Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id
    delete_active_chat(user_id)
    
    # Очищаємо кнопку знизу
    temp_msg = await message.answer("🔄 Очищення чату...", reply_markup=ReplyKeyboardRemove())
    
    # Отримуємо всі ID повідомлень (включно з історією) і видаляємо їх з екрану
    msg_ids_to_delete = get_and_clear_chat_msgs(user_id)
    
    msg_ids_to_delete.append(message.message_id)
    msg_ids_to_delete.append(temp_msg.message_id)

    for mid in msg_ids_to_delete:
        with suppress(TelegramBadRequest):
            await bot.delete_message(chat_id=user_id, message_id=mid)

    # Повертаємо головне меню
    data = await state.get_data()
    role = data.get("role", "passenger")
    
    new_menu = await message.answer(
        f"✅ <b>Чат завершено.</b>\nМеню {role}:", 
        reply_markup=kb_menu(role), 
        parse_mode="HTML"
    )
    await state.update_data(last_msg_id=new_menu.message_id)


# ==========================================
# 📨 3. ПЕРЕСИЛАННЯ (Із записом в історію)
# ==========================================

@router.message(F.text & ~F.text.startswith("/"))
@router.message(F.photo | F.voice | F.video | F.location | F.sticker) 
async def chat_relay_handler(message: types.Message, bot: Bot):
    user_id = message.from_user.id
    partner_id = get_active_chat_partner(user_id)
    
    if not partner_id:
        return

    # Зберігаємо повідомлення відправника для очищення
    save_chat_msg(user_id, message.message_id)

    sender = get_user(user_id)
    sender_name = sender['name'] if sender else "Співрозмовник"

    try:
        sent_msg = None
        
        # Пересилаємо
        if message.text:
            msg_text = f"👤 <b>{sender_name}:</b>\n{message.text}"
            sent_msg = await bot.send_message(partner_id, msg_text, reply_markup=kb_chat_actions(), parse_mode="HTML")
            
            # 🔥 ЗБЕРІГАЄМО ТЕКСТ В ІСТОРІЮ БД
            save_message_to_history(user_id, partner_id, message.text)
            
        else:
            sent_msg = await message.copy_to(
                chat_id=partner_id,
                caption=f"👤 <b>{sender_name}</b> надіслав файл.",
                reply_markup=kb_chat_actions(),
                parse_mode="HTML"
            )
            # Файли помічаємо в історії просто як [Файл]
            save_message_to_history(user_id, partner_id, "[Медіа-файл]")
        
        # Зберігаємо повідомлення отримувача для очищення у нього
        if sent_msg:
            save_chat_msg(partner_id, sent_msg.message_id)

    except TelegramForbiddenError:
        await message.answer("❌ Користувач заблокував бота.")
        delete_active_chat(user_id)
        
    except Exception:
        pass
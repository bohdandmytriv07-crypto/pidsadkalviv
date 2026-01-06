import asyncio
from contextlib import suppress
from aiogram import Router, F, types, Bot
from aiogram.types import ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.context import FSMContext

# Імпорти
from database import (
    set_active_chat, get_active_chat_partner, delete_active_chat, get_user,
    save_chat_msg, get_and_clear_chat_msgs # 👈 Додано нові функції
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

    # Повідомлення про старт
    msg = await call.message.answer(
        f"💬 <b>Чат з {target_user['name']}</b>\n"
        f"Пишіть повідомлення, я передам.", 
        reply_markup=kb_chat_actions(), 
        parse_mode="HTML"
    )
    
    # 🔥 Зберігаємо ID системного повідомлення
    save_chat_msg(my_id, msg.message_id)
    
    set_active_chat(target_user_id, my_id) 


# ==========================================
# 🛑 2. ЗАВЕРШЕННЯ ЧАТУ (Очищення)
# ==========================================

@router.message(F.text == "❌ Завершити чат")
async def end_chat_text_handler(message: types.Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id
    delete_active_chat(user_id)
    
    # 1. Очищаємо кнопку знизу (через тимчасове повідомлення)
    temp_msg = await message.answer("🔄 Очищення чату...", reply_markup=ReplyKeyboardRemove())
    
    # 2. Отримуємо список всіх повідомлень з бази
    msg_ids_to_delete = get_and_clear_chat_msgs(user_id)
    
    # Додаємо в список на видалення саме це повідомлення "Завершити чат" і тимчасове
    msg_ids_to_delete.append(message.message_id)
    msg_ids_to_delete.append(temp_msg.message_id)

    # 3. Видаляємо ВСІ повідомлення циклом
    for mid in msg_ids_to_delete:
        with suppress(TelegramBadRequest):
            await bot.delete_message(chat_id=user_id, message_id=mid)

    # 4. Повертаємо головне меню
    data = await state.get_data()
    role = data.get("role", "passenger")
    
    new_menu = await message.answer(
        f"✅ <b>Чат завершено.</b>\nМеню {role}:", 
        reply_markup=kb_menu(role), 
        parse_mode="HTML"
    )
    await state.update_data(last_msg_id=new_menu.message_id)


# ==========================================
# 📨 3. ПЕРЕСИЛАННЯ (Зі збереженням ID)
# ==========================================

@router.message(F.text & ~F.text.startswith("/"))
@router.message(F.photo | F.voice | F.video | F.location | F.sticker) 
async def chat_relay_handler(message: types.Message, bot: Bot):
    user_id = message.from_user.id
    partner_id = get_active_chat_partner(user_id)
    
    if not partner_id:
        return

    # 🔥 1. Зберігаємо повідомлення ВІДПРАВНИКА (щоб видалити у нього потім)
    save_chat_msg(user_id, message.message_id)

    sender = get_user(user_id)
    sender_name = sender['name'] if sender else "Співрозмовник"

    try:
        sent_msg = None
        
        # Пересилаємо
        if message.text:
            msg_text = f"👤 <b>{sender_name}:</b>\n{message.text}"
            sent_msg = await bot.send_message(partner_id, msg_text, reply_markup=kb_chat_actions(), parse_mode="HTML")
        else:
            sent_msg = await message.copy_to(
                chat_id=partner_id,
                caption=f"👤 <b>{sender_name}</b> надіслав файл.",
                reply_markup=kb_chat_actions(),
                parse_mode="HTML"
            )
        
        # 🔥 2. Зберігаємо повідомлення ОТРИМУВАЧА (щоб видалити у нього, коли він натисне вихід)
        if sent_msg:
            save_chat_msg(partner_id, sent_msg.message_id)

    except TelegramForbiddenError:
        await message.answer("❌ Користувач заблокував бота.")
        delete_active_chat(user_id)
        
    except Exception:
        pass
from contextlib import suppress
from aiogram import Router, F, types, Bot
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from aiogram.exceptions import TelegramBadRequest

from database import (
    is_user_banned, get_and_clear_chat_msgs, 
    delete_active_chat, check_terms_status, accept_terms, save_user
)
from keyboards import kb_main_role, kb_menu
# 🔥 Додаємо delete_prev_msg для красивого чату
from utils import clean_user_input, update_or_send_msg, delete_messages_list, delete_prev_msg
from states import SupportStates
from config import SUPPORT_CHANNEL_ID

router = Router()

# ==========================================
# 🏁 START / MENU
# ==========================================

@router.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext, bot: Bot):
    await state.clear() 
    
    # Видаляємо стару клавіатуру Reply (якщо була)
    try:
        temp_msg = await message.answer("🔄 Завантаження...", reply_markup=ReplyKeyboardRemove())
        await temp_msg.delete()
    except: pass

    user_id = message.from_user.id
    
    # 1. Реєстрація
    args = message.text.split(maxsplit=1)
    argument = args[1] if len(args) > 1 else None
    ref_source = argument if argument and not argument.startswith("book_") else None
    
    username = f"@{message.from_user.username}" if message.from_user.username else None
    save_user(user_id, message.from_user.full_name, username, ref_source=ref_source)
    
    # 2. Бан
    if is_user_banned(user_id):
        await message.answer("⛔ <b>Ви заблоковані адміністратором.</b>", parse_mode="HTML")
        return

    # 3. Чистка
    await _clean_chat_interface(user_id, state, bot, message.chat.id)

    # 4. Deep Link (бронювання за посиланням)
    target_trip_id = None
    if argument and argument.startswith("book_"):
        target_trip_id = argument.replace("book_", "")

    # 5. Угода
    if check_terms_status(user_id):
        if target_trip_id:
            from handlers.passenger import show_trip_preview
            await show_trip_preview(message, state, target_trip_id)
        else:
            await _show_role_menu(message, state)
    else:
        if target_trip_id:
            await state.update_data(pending_trip_id=target_trip_id)

        terms_text = (
            f"👋 <b>Вітаємо у спільноті!</b>\n\n"
            f"📋 <b>Угода користувача:</b>\n"
            f"1. Ми надаємо інформаційні послуги.\n"
            f"2. Перевіряйте попутників самостійно.\n\n"
            f"<i>Натисніть кнопку, щоб продовжити.</i>"
        )
        kb_terms = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Я погоджуюсь", callback_data="terms_ok")]])
        msg = await message.answer(terms_text, reply_markup=kb_terms, parse_mode="HTML")
        await state.update_data(last_msg_id=msg.message_id)

@router.callback_query(F.data == "terms_ok")
async def terms_accepted_handler(call: types.CallbackQuery, state: FSMContext):
    accept_terms(call.from_user.id, call.from_user.full_name)
    await call.answer("Доступ відкрито ✅")
    with suppress(TelegramBadRequest): await call.message.delete()
    
    data = await state.get_data()
    pending_trip = data.get("pending_trip_id")
    
    if pending_trip:
        await state.update_data(pending_trip_id=None)
        from handlers.passenger import show_trip_preview
        await show_trip_preview(call.message, state, pending_trip)
    else:
        await _show_role_menu(call.message, state)

async def _show_role_menu(message: types.Message, state: FSMContext):
    new_msg = await message.answer(
        "👋 <b>Вітаємо!</b>\nОберіть вашу роль:",
        reply_markup=kb_main_role(), parse_mode="HTML"
    )
    await state.update_data(last_msg_id=new_msg.message_id)

async def _clean_chat_interface(user_id: int, state: FSMContext, bot: Bot, chat_id: int):
    await delete_messages_list(state, bot, chat_id, "trip_msg_ids")
    await delete_messages_list(state, bot, chat_id, "booking_msg_ids")
    await delete_messages_list(state, bot, chat_id, "search_msg_ids")
    
    data = await state.get_data()
    if data.get("last_msg_id"):
        with suppress(TelegramBadRequest):
            await bot.delete_message(chat_id=chat_id, message_id=data["last_msg_id"])
    
    delete_active_chat(user_id) 
    ids_to_delete = get_and_clear_chat_msgs(user_id)
    for mid in ids_to_delete:
        with suppress(TelegramBadRequest):
            await bot.delete_message(chat_id=chat_id, message_id=mid)
            
    await state.clear()

@router.callback_query(F.data == "back_start")
async def back_to_start_handler(call: types.CallbackQuery, state: FSMContext):
    await _clean_chat_interface(call.from_user.id, state, call.bot, call.message.chat.id)
    await update_or_send_msg(call.bot, call.message.chat.id, state, "👋 <b>Головне меню</b>\nОберіть роль:", kb_main_role())

@router.callback_query(F.data.startswith("role_"))
async def set_role_handler(call: types.CallbackQuery, state: FSMContext):
    role = call.data.split("_")[1]
    await state.update_data(role=role)
    menu_title = "Водія 🚖" if role == "driver" else "Пасажира 🚶"
    await update_or_send_msg(call.bot, call.message.chat.id, state, f"Меню {menu_title}:", kb_menu(role))

@router.callback_query(F.data == "menu_home")
async def back_to_menu_handler(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    # Очищаємо списки
    await delete_messages_list(state, bot, call.message.chat.id, "trip_msg_ids")
    await delete_messages_list(state, bot, call.message.chat.id, "booking_msg_ids")
    await delete_messages_list(state, bot, call.message.chat.id, "search_msg_ids")
    
    # Видаляємо саме повідомлення з кнопкою
    with suppress(TelegramBadRequest): await call.message.delete()
    await state.update_data(last_msg_id=None)
    delete_active_chat(call.from_user.id)
    
    # Відновлюємо меню
    data = await state.get_data()
    role = data.get("role", "passenger")
    menu_title = "Водія 🚖" if role == "driver" else "Пасажира 🚶"
    
    await update_or_send_msg(bot, call.message.chat.id, state, f"Меню {menu_title}:", kb_menu(role))

# ==========================================
# 🆘 ПІДТРИМКА (Оновлена логіка: багато повідомлень)
# ==========================================

@router.message(Command("support"))
async def cmd_support(message: types.Message, state: FSMContext, bot: Bot):
    await _start_support(message.chat.id, state, bot)

@router.callback_query(F.data == "support")
async def cb_support(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    await _start_support(call.message.chat.id, state, bot)
    await call.answer()

async def _start_support(chat_id, state, bot):
    await delete_messages_list(state, bot, chat_id, "trip_msg_ids")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Скасувати", callback_data="support_cancel")]])
    await state.set_state(SupportStates.waiting_for_message)
    
    # 🔥 Змінили текст, щоб користувач знав, що можна слати багато
    text = (
        "🆘 <b>Підтримка</b>\n\n"
        "Опишіть проблему або надішліть фото/відео.\n"
        "📸 <b>Можна надсилати декілька повідомлень підряд!</b>\n"
        "Коли закінчите — натисніть кнопку внизу."
    )
    await update_or_send_msg(bot, chat_id, state, text, kb)

@router.callback_query(F.data == "support_cancel")
async def support_cancel(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    await state.clear()
    await back_to_menu_handler(call, state, bot)

# 🔥 НОВА ЛОГІКА: Кнопка "Завершити"
@router.callback_query(F.data == "support_finish")
async def support_finish(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    await state.clear()
    await call.answer("Запит надіслано!", show_alert=True)
    
    # Повертаємо користувача в меню
    await back_to_menu_handler(call, state, bot)

@router.message(SupportStates.waiting_for_message)
async def process_support(message: types.Message, state: FSMContext, bot: Bot):
    user = message.from_user
    text = message.text or message.caption or ""
    
    if len(text) > 1000:
        await message.answer("⚠️ <b>Текст занадто довгий!</b> (макс 1000 символів)")
        return

    # Заголовок для адміна
    header = f"🆘 <b>Тікет від:</b> {user.full_name} (ID: <code>{user.id}</code>)\n"
    if user.username: header += f"User: @{user.username}\n\n"
    else: header += "\n"

    try:
        # Відправка адміну
        if message.photo:
            await bot.send_photo(SUPPORT_CHANNEL_ID, message.photo[-1].file_id, caption=header + text, parse_mode="HTML")
        elif message.video:
            await bot.send_video(SUPPORT_CHANNEL_ID, message.video.file_id, caption=header + text, parse_mode="HTML")
        elif message.text:
            await bot.send_message(SUPPORT_CHANNEL_ID, header + text, parse_mode="HTML")
        else:
            await message.answer("⚠️ Тільки текст, фото або відео.")
            return
        
     
        
        await delete_prev_msg(state, bot, message.chat.id)
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Це все, надіслати", callback_data="support_finish")]
        ])
        
        # Це повідомлення буде "стрибати" вниз після кожного нового фото
        msg = await message.answer(
            "✅ <b>Збережено!</b>\nНадішліть ще фото/текст або натисніть кнопку:", 
            reply_markup=kb, 
            parse_mode="HTML"
        )
        await state.update_data(last_msg_id=msg.message_id)
    
    except Exception as e:
        print(f"Support Error: {e}")
        await message.answer(f"❌ Помилка: {e}")
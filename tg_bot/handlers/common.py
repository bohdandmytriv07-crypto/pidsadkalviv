import asyncio
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
from utils import clean_user_input, update_or_send_msg, delete_messages_list, delete_prev_msg
from states import SupportStates
from config import SUPPORT_CHANNEL_ID

router = Router()

# ==========================================
# 🏁 START / MENU
# ==========================================

# 📂 common.py

# Додай ці імпорти зверху, якщо їх немає
from aiogram.exceptions import TelegramBadRequest
from contextlib import suppress

# ==========================================
# 🏁 БЕЗПЕЧНИЙ START
# ==========================================

@router.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext, bot: Bot):
    # Перевіряємо поточний стан користувача
    current_state = await state.get_state()
    
    # Якщо у юзера є активний стан (він щось заповнює), питаємо підтвердження
    if current_state: 
        kb_reset = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚠️ Так, скинути все", callback_data="confirm_restart")],
            [InlineKeyboardButton(text="🔙 Ні, я продовжую", callback_data="hide_msg")]
        ])
        await message.answer(
            "⚠️ <b>Ви зараз заповнюєте дані.</b>\nЯкщо почати спочатку, весь прогрес буде втрачено.", 
            reply_markup=kb_reset, 
            parse_mode="HTML"
        )
        return

    # Якщо станів немає — запускаємо звичайну логіку
    await _execute_start(message, state, bot)

@router.callback_query(F.data == "confirm_restart")
async def confirm_restart_handler(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    # Видаляємо повідомлення з питанням
    with suppress(TelegramBadRequest): await call.message.delete()
    
    # Запускаємо логіку старту, передаючи користувача з callback
    # Ми емулюємо пусте повідомлення "/start", щоб скинути все в меню
    await _execute_start(call.message, state, bot, override_user=call.from_user, force_text="/start")

# 👇 Твоя оригінальна логіка перенесена сюди
async def _execute_start(message: types.Message, state: FSMContext, bot: Bot, override_user=None, force_text=None):
    await state.clear() 
    
    try:
        temp_msg = await message.answer("🔄 Завантаження...", reply_markup=ReplyKeyboardRemove())
        await temp_msg.delete()
    except: pass

    # Визначаємо User Object (якщо виклик з кнопки - беремо override_user)
    user_obj = override_user if override_user else message.from_user
    user_id = user_obj.id
    
    # Визначаємо текст (якщо виклик з кнопки - беремо force_text)
    text_content = force_text if force_text else message.text
    
    args = text_content.split(maxsplit=1)
    argument = args[1] if len(args) > 1 else None
    ref_source = argument if argument and not argument.startswith("book_") else None
    
    username = f"@{user_obj.username}" if user_obj.username else None
    save_user(user_id, user_obj.full_name, username, ref_source=ref_source)
    
    if is_user_banned(user_id):
        await message.answer("⛔ <b>Ви заблоковані адміністратором.</b>", parse_mode="HTML")
        return

    await _clean_chat_interface(user_id, state, bot, message.chat.id)

    target_trip_id = None
    if argument and argument.startswith("book_"):
        target_trip_id = argument.replace("book_", "")

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
            f"👋 <b>Вітаємо у спільноті «Підсадка Львів»!</b> 🇺🇦\n\n"
            f"Це простір, де ми допомагаємо один одному:\n"
            f"🚘 <b>Водії</b> — економлять на пальному та знаходять компанію.\n"
            f"🎒 <b>Пасажири</b> — подорожують швидко та з комфортом.\n\n"
            f"☝️ <b>Важливо:</b> Ми не служба таксі, ми — спільнота. Тут усе будується на взаємоповазі та довірі.\n\n"
            f"Щоб уникнути непорозумінь, будь ласка, перегляньте наші домовленості перед початком:"
        )
        
        LINK_RULES = "https://t.me/pidsadkalvivinfo" 
        LINK_PRIVACY = "https://telegra.ph/Ugoda-koristuvacha-ta-Pol%D1%96tika-konf%D1%96denc%D1%96jnost%D1%96-serv%D1%96su-P%D1%96dsadka-Lv%D1%96v-01-30"
        
        kb_welcome = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📜 Правила спільноти", url=LINK_RULES)],
            [InlineKeyboardButton(text="🔒 Умови конфіденційності", url=LINK_PRIVACY)],
            [InlineKeyboardButton(text="🚀 Поїхали! (Приймаю умови)", callback_data="terms_ok")]
        ])
        
        msg = await message.answer(terms_text, reply_markup=kb_welcome, parse_mode="HTML")
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
    # Чистимо всі списки
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
    await delete_messages_list(state, bot, call.message.chat.id, "trip_msg_ids")
    await delete_messages_list(state, bot, call.message.chat.id, "booking_msg_ids")
    await delete_messages_list(state, bot, call.message.chat.id, "search_msg_ids")
    
    with suppress(TelegramBadRequest): await call.message.delete()
    await state.update_data(last_msg_id=None)
    delete_active_chat(call.from_user.id)
    
    data = await state.get_data()
    role = data.get("role", "passenger")
    menu_title = "Водія 🚖" if role == "driver" else "Пасажира 🚶"
    
    await update_or_send_msg(bot, call.message.chat.id, state, f"Меню {menu_title}:", kb_menu(role))

# ==========================================
# 🆘 ПІДТРИМКА (Оновлено)
# ==========================================

@router.message(Command("support"))
async def cmd_support(message: types.Message, state: FSMContext, bot: Bot):
    await _start_support(message.chat.id, state, bot)

@router.callback_query(F.data == "support")
async def cb_support(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    await _start_support(call.message.chat.id, state, bot)
    await call.answer()

async def _start_support(chat_id, state, bot):
    # Очищаємо попередні списки
    await delete_messages_list(state, bot, chat_id, "trip_msg_ids")
    
    # Створюємо пустий список для повідомлень юзера в сапорті
    await state.update_data(support_user_msgs=[]) 
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Скасувати", callback_data="back_start")]])
    await state.set_state(SupportStates.waiting_for_message)
    
    text = (
        "🆘 <b>Підтримка</b>\n\n"
        "Опишіть проблему або надішліть фото/відео.\n"
        "📸 <b>Можна надсилати багато фото одразу!</b>\n"
        "Натисніть кнопку внизу, коли закінчите."
    )
    await update_or_send_msg(bot, chat_id, state, text, kb)

@router.callback_query(F.data == "support_finish")
async def support_finish(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    await call.answer("Запит надіслано!", show_alert=True)
    
    # 🔥 FIX 2: Видаляємо всі повідомлення, які юзер надіслав у тікет
    chat_id = call.message.chat.id
    data = await state.get_data()
    user_msgs = data.get("support_user_msgs", [])
    
    for mid in user_msgs:
        with suppress(Exception):
            await bot.delete_message(chat_id, mid)
            await asyncio.sleep(0.05) # Невеличка затримка для стабільності
            
    # Повертаємо на вибір ролі
    await back_to_start_handler(call, state)

@router.message(SupportStates.waiting_for_message)
async def process_support(message: types.Message, state: FSMContext, bot: Bot):
    user = message.from_user
    text = message.text or message.caption or ""

    # Додаємо ID повідомлення в список для видалення в кінці
    data = await state.get_data()
    current_list = data.get("support_user_msgs", [])
    current_list.append(message.message_id)
    await state.update_data(support_user_msgs=current_list)

    # Заголовок
    header = f"🆘 <b>Тікет від:</b> {user.full_name} (ID: <code>{user.id}</code>)\n"
    if user.username: header += f"User: @{user.username}\n\n"
    else: header += "\n"

    try:
        # Пересилаємо адміну
        # Використовуємо copy_to, щоб зберегти тип контенту (фото/відео/текст)
        await message.copy_to(SUPPORT_CHANNEL_ID, caption=header + text, parse_mode="HTML")
        
        # 🔥 Оновлюємо інтерфейс (кнопку "Завершити")
        # Робимо це хитро: не видаляємо і шлемо нове, а пробуємо редагувати старе повідомлення бота,
        # щоб воно завжди було знизу.
        
        last_bot_msg_id = data.get("last_msg_id")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Надіслати все і вийти", callback_data="support_finish")]
        ])
        
        # Якщо це перше повідомлення - оновлюємо текст бота, щоб юзер бачив, що процес йде
        if len(current_list) == 1:
             msg = await bot.send_message(
                message.chat.id,
                "✅ <b>Отримано!</b>\nНадсилайте ще або завершіть:", 
                reply_markup=kb, 
                parse_mode="HTML"
            )
           
             await delete_prev_msg(state, bot, message.chat.id)
             await state.update_data(last_msg_id=msg.message_id)
             
    except Exception as e:
        print(f"Support Error: {e}")

# ==========================================
# 🗑 УНІВЕРСАЛЬНА КНОПКА "ЗРОЗУМІЛО" (Видаляє повідомлення)
# ==========================================
@router.callback_query(F.data == "hide_msg")
async def global_hide_msg(call: types.CallbackQuery):
    with suppress(TelegramBadRequest):
        await call.message.delete()
    await call.answer()
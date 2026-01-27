from contextlib import suppress
from aiogram import Router, F, types, Bot
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

from database import (
    is_user_banned, get_and_clear_chat_msgs, 
    delete_active_chat, check_terms_status, accept_terms, get_connection
)
from keyboards import kb_main_role, kb_menu
from utils import clean_user_input, update_or_send_msg, delete_messages_list

from handlers.passenger import show_trip_preview 
from states import SupportStates
from config import SUPPORT_CHANNEL_ID

router = Router()

# ==========================================
# 🆘 ПІДТРИМКА
# ==========================================

@router.message(Command("support"))
async def cmd_support(message: types.Message, state: FSMContext, bot: Bot):
    await _start_support_scenario(message, state, bot, message.chat.id)

@router.callback_query(F.data == "support")
async def callback_support(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    await _start_support_scenario(call.message, state, bot, call.message.chat.id)
    await call.answer()

async def _start_support_scenario(message: types.Message, state: FSMContext, bot: Bot, chat_id: int):
    await delete_messages_list(state, bot, chat_id, "trip_msg_ids")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Скасувати", callback_data="support_cancel")]])
    text = (
        "🆘 <b>Служба підтримки</b>\n\n"
        "Опишіть вашу проблему, знайдену помилку або пропозицію.\n"
        "Можете прикріпити <b>скріншот</b> або <b>фото</b>.\n\n"
        "<i>Напишіть повідомлення та надішліть його сюди 👇</i>"
    )
    
    await state.set_state(SupportStates.waiting_for_message)
    await update_or_send_msg(bot, chat_id, state, text, kb)


@router.callback_query(F.data == "support_cancel")
async def support_cancel(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    await state.clear()
    await back_to_menu_handler(call, state, bot)


@router.message(SupportStates.waiting_for_message)
async def process_support_message(message: types.Message, state: FSMContext, bot: Bot):
    await clean_user_input(message)
    
    # 🔥 КРОК 1: Зберігаємо ID старого повідомлення (меню підтримки)
    data = await state.get_data()
    last_msg_id = data.get("last_msg_id")
    
    user = message.from_user
    username = f"@{user.username}" if user.username else "без юзернейму"
    user_link = f"<a href='tg://user?id={user.id}'>{user.full_name}</a>"
    
    caption_header = (
        f"🆘 <b>Новий тікет!</b>\n"
        f"👤 Від: {user_link} ({username})\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"➖➖➖➖➖➖➖\n"
    )

    try:
        if message.photo:
            photo_id = message.photo[-1].file_id
            text = message.caption if message.caption else "<i>(без опису)</i>"
            full_text = caption_header + text
            await bot.send_photo(chat_id=SUPPORT_CHANNEL_ID, photo=photo_id, caption=full_text, parse_mode="HTML")
        elif message.text:
            full_text = caption_header + message.text
            await bot.send_message(chat_id=SUPPORT_CHANNEL_ID, text=full_text, parse_mode="HTML")
        else:
            # Якщо повідомлення не підходить, просто ігноруємо, не очищаючи стан
            await update_or_send_msg(bot, message.chat.id, state, "⚠️ Будь ласка, надішліть текст або фото.", None)
            return

        # 🔥 КРОК 2: Очищаємо стан (скидається все)
        await state.clear()
        
        # 🔥 КРОК 3: Відновлюємо last_msg_id, щоб бот знав, що редагувати
        if last_msg_id:
            await state.update_data(last_msg_id=last_msg_id)
        
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 В меню", callback_data="menu_home")]])
        await update_or_send_msg(
            bot, message.chat.id, state, 
            "✅ <b>Повідомлення надіслано!</b>\nАдміністратор отримав ваш запит.", 
            kb
        )

    except Exception as e:
        print(f"Support Error: {e}")
        await update_or_send_msg(bot, message.chat.id, state, f"❌ Помилка: {e}", None)


# ==========================================
# 🏁 START / MENU
# ==========================================

@router.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext, bot: Bot):
    await clean_user_input(message)
    user_id = message.from_user.id
    args = message.text.split(maxsplit=1)
    argument = args[1] if len(args) > 1 else None
    
    conn = get_connection()
    cursor = conn.cursor()
    exist = cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)).fetchone()
    
    ref_source = argument if argument and not argument.startswith("book_") else None
    
    if not exist:
        username = f"@{message.from_user.username}" if message.from_user.username else None
        cursor.execute('''
            INSERT INTO users (user_id, username, name, phone, ref_source)
            VALUES (?, ?, ?, '-', ?)
        ''', (user_id, username, message.from_user.full_name, ref_source))
        conn.commit()
    else:
        cursor.execute("UPDATE users SET is_blocked_bot = 0 WHERE user_id = ?", (user_id,))
        conn.commit()
    conn.close()
    
    if is_user_banned(user_id):
        await message.answer("⛔ <b>Ви заблоковані.</b>", parse_mode="HTML")
        return

    await _clean_chat_interface(user_id, state, bot, message.chat.id)

    target_trip_id = None
    if argument and argument.startswith("book_"):
        target_trip_id = argument.replace("book_", "")

    if check_terms_status(user_id):
        if target_trip_id:
            await show_trip_preview(message, state, target_trip_id)
        else:
            await _show_role_menu(message, state)
    else:
        if target_trip_id:
            await state.update_data(pending_trip_id=target_trip_id)

        terms_text = (
            f"👋 <b>Вітаємо у спільноті!</b>\n\n"
            f"📋 <b>Угода користувача:</b>\n"
            f"1. Ми не є перевізником, а лише надаємо інформацію.\n"
            f"2. Ви погоджуєтесь на обробку персональних даних.\n"
            f"3. Будьте обережні та перевіряйте попутників.\n\n"
            f"<i>Натискаючи кнопку, ви погоджуєтесь з правилами.</i>"
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
    await delete_messages_list(state, bot, call.message.chat.id, "trip_msg_ids")
    await delete_messages_list(state, bot, call.message.chat.id, "booking_msg_ids")
    await delete_messages_list(state, bot, call.message.chat.id, "search_msg_ids")
    
    # 🔥 КРОК 4: Агресивна очистка при поверненні в меню
    # Видаляємо те повідомлення, де натиснули кнопку "В меню"
    with suppress(TelegramBadRequest):
        await call.message.delete()
    
    # Очищаємо пам'ять про це повідомлення, щоб update_or_send_msg надіслав НОВЕ чисте меню
    await state.update_data(last_msg_id=None)
    
    delete_active_chat(call.from_user.id)
    
    data = await state.get_data()
    role = data.get("role", "passenger")
    menu_title = "Водія 🚖" if role == "driver" else "Пасажира 🚶"
    await update_or_send_msg(bot, call.message.chat.id, state, f"Меню {menu_title}:", kb_menu(role))
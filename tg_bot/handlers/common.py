from contextlib import suppress
from aiogram import Router, F, types, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

# Імпорти з ваших файлів
from database import is_user_banned, save_user, get_and_clear_chat_msgs, delete_active_chat, get_user
from keyboards import kb_main_role, kb_menu
from utils import clean_user_input, update_or_send_msg, delete_prev_msg

router = Router()

# ==========================================
# 🚀 СТАРТ ТА ПЕРЕВІРКА ДОСТУПУ
# ==========================================

@router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext, bot: Bot):
    # 1. Видаляємо саме повідомлення "/start" від користувача
    await clean_user_input(message)
    
    user_id = message.from_user.id
    
    # Зберігаємо юзера, не затираючи телефон
    existing_user = get_user(user_id)
    current_phone = existing_user['phone'] if existing_user else "-"
    
    save_user(
        user_id, 
        message.from_user.full_name, 
        current_phone 
    )
    
    # Перевірка бану
    if is_user_banned(user_id):
        await message.answer("⛔ <b>Ви заблоковані.</b>\nЗверніться до підтримки.", parse_mode="HTML")
        return

    # --- ГЕНЕРАЛЬНЕ ПРИБИРАННЯ ---
    data = await state.get_data()
    
    ids_to_delete = []
    if data.get("last_interface_id"): ids_to_delete.append(data.get("last_interface_id"))
    if data.get("last_msg_id"): ids_to_delete.append(data.get("last_msg_id"))
    ids_to_delete.extend(data.get("trip_msg_ids", []))
    ids_to_delete.extend(data.get("booking_msg_ids", []))
    
    delete_active_chat(user_id) 
    ids_to_delete.extend(get_and_clear_chat_msgs(user_id)) 

    for mid in ids_to_delete:
        if mid:
            with suppress(TelegramBadRequest):
                await bot.delete_message(chat_id=message.chat.id, message_id=mid)

    # Скидаємо стан
    await state.clear()

    # Відправляємо нове головне меню і зберігаємо його ID
    new_msg = await message.answer(
        "👋 <b>Вітаємо у RideBot!</b>\nОберіть вашу роль:",
        reply_markup=kb_main_role(),
        parse_mode="HTML"
    )
    # Зберігаємо як last_msg_id, щоб update_or_send_msg міг його редагувати
    await state.update_data(last_msg_id=new_msg.message_id)


# ==========================================
# 🔄 НАВІГАЦІЯ (КНОПКИ "НАЗАД")
# ==========================================

@router.callback_query(F.data == "back_start")
async def back_to_start_handler(call: types.CallbackQuery, state: FSMContext):
    """Повернення до вибору ролі (Водій/Пасажир)."""
    # Запам'ятовуємо ID поточного повідомлення
    prev_msg_id = call.message.message_id
    
    await state.clear()
    # Відновлюємо ID в чистому стані
    await state.update_data(last_msg_id=prev_msg_id)
    
    await update_or_send_msg(
        call.bot, call.message.chat.id, state,
        "👋 <b>Головне меню</b>\nОберіть роль:",
        kb_main_role()
    )


@router.callback_query(F.data.startswith("role_"))
async def set_role_handler(call: types.CallbackQuery, state: FSMContext):
    """Встановлення ролі (Водій або Пасажир) і показ відповідного меню."""
    role = call.data.split("_")[1]
    await state.update_data(role=role)
    
    menu_title = "Водія 🚖" if role == "driver" else "Пасажира 🚶"
    
    await update_or_send_msg(
        call.bot, call.message.chat.id, state,
        f"Меню {menu_title}:",
        kb_menu(role)
    )


@router.callback_query(F.data == "menu_home")
async def back_to_menu_handler(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    """
    Повертає в меню поточної ролі.
    ВАЖЛИВО: Ця функція також чистить екран від чатів та списків.
    """
    # Запам'ятовуємо ID поточного повідомлення (меню/кнопки "назад"), яке ми натиснули
    prev_msg_id = call.message.message_id
    
    data = await state.get_data()
    role = data.get("role", "passenger") # За замовчуванням пасажир
    
    # Збираємо сміття (старі списки поїздок тощо)
    ids_to_clean = []
    ids_to_clean.extend(data.get("trip_msg_ids", []))
    ids_to_clean.extend(data.get("booking_msg_ids", []))
    
    # Видаляємо все зайве, КРІМ поточного повідомлення (бо ми його відредагуємо)
    for msg_id in ids_to_clean:
        if msg_id != prev_msg_id:
            with suppress(TelegramBadRequest):
                await bot.delete_message(chat_id=call.message.chat.id, message_id=msg_id)

    # Якщо був чат - виходимо з нього
    delete_active_chat(call.from_user.id)

    # Очищаємо пам'ять, АЛЕ відновлюємо ID повідомлення і роль
    await state.clear()
    await state.update_data(role=role, last_msg_id=prev_msg_id)
    
    menu_title = "Водія 🚖" if role == "driver" else "Пасажира 🚶"
    
    # Редагуємо поточне повідомлення на Головне Меню
    await update_or_send_msg(
        bot, call.message.chat.id, state,
        f"Меню {menu_title}:",
        kb_menu(role)
    )
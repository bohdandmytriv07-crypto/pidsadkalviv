from contextlib import suppress
from aiogram import Router, F, types, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

# Імпорти з ваших файлів
from database import is_user_banned, save_user, get_and_clear_chat_msgs, delete_active_chat
from keyboards import kb_main_role, kb_menu
from utils import clean_user_input

router = Router()

# ==========================================
# 🚀 СТАРТ ТА ПЕРЕВІРКА ДОСТУПУ
# ==========================================

@router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext, bot: Bot):
    # 1. Видаляємо саме повідомлення "/start" від користувача
    await clean_user_input(message)
    
    user_id = message.from_user.id

    # 2. Зберігаємо/Оновлюємо користувача в базі
    save_user(
        user_id, 
        message.from_user.full_name, 
        "-" # Телефон поки не знаємо, оновиться пізніше
    )
    
    # 3. Перевірка бану
    if is_user_banned(user_id):
        await message.answer("⛔ <b>Ви заблоковані.</b>\nЗверніться до підтримки.", parse_mode="HTML")
        return

    # 4. --- ГЕНЕРАЛЬНЕ ПРИБИРАННЯ ---
    # Це очистить екран від старих меню, чатів та списків поїздок
    data = await state.get_data()
    
    ids_to_delete = []
    
    # а) Старі інтерфейси
    if data.get("last_interface_id"): ids_to_delete.append(data.get("last_interface_id"))
    if data.get("last_msg_id"): ids_to_delete.append(data.get("last_msg_id"))
    
    # б) Списки (поїздки водія, бронювання пасажира)
    ids_to_delete.extend(data.get("trip_msg_ids", []))
    ids_to_delete.extend(data.get("booking_msg_ids", []))
    
    # в) Чати (якщо бот був у режимі чату)
    delete_active_chat(user_id) # Видаляємо статус "в чаті"
    ids_to_delete.extend(get_and_clear_chat_msgs(user_id)) # Видаляємо повідомлення чату

    # Виконуємо масове видалення
    for mid in ids_to_delete:
        if mid:
            with suppress(TelegramBadRequest):
                await bot.delete_message(chat_id=message.chat.id, message_id=mid)

    # 5. Скидаємо стан (FSM)
    await state.clear()

    # 6. Відправляємо головне меню вибору ролі
    new_msg = await message.answer(
        "👋 <b>Вітаємо у RideBot!</b>\nОберіть вашу роль:",
        reply_markup=kb_main_role(),
        parse_mode="HTML"
    )
    # Зберігаємо ID меню, щоб потім його теж можна було видалити/оновити
    await state.update_data(last_interface_id=new_msg.message_id)


# ==========================================
# 🔄 НАВІГАЦІЯ (КНОПКИ "НАЗАД")
# ==========================================

@router.callback_query(F.data == "back_start")
async def back_to_start_handler(call: types.CallbackQuery, state: FSMContext):
    """Повернення до вибору ролі (Водій/Пасажир)."""
    await state.clear()
    
    try:
        msg = await call.message.edit_text(
            "👋 <b>Головне меню</b>\nОберіть роль:",
            reply_markup=kb_main_role(),
            parse_mode="HTML"
        )
        await state.update_data(last_interface_id=msg.message_id)
    except TelegramBadRequest:
        await call.message.delete()
        msg = await call.message.answer(
            "👋 <b>Головне меню</b>\nОберіть роль:",
            reply_markup=kb_main_role(),
            parse_mode="HTML"
        )
        await state.update_data(last_interface_id=msg.message_id)


@router.callback_query(F.data.startswith("role_"))
async def set_role_handler(call: types.CallbackQuery, state: FSMContext):
    """Встановлення ролі (Водій або Пасажир) і показ відповідного меню."""
    role = call.data.split("_")[1]
    await state.update_data(role=role)
    
    menu_title = "Водія 🚖" if role == "driver" else "Пасажира 🚶"
    
    try:
        msg = await call.message.edit_text(
            f"Меню {menu_title}:",
            reply_markup=kb_menu(role),
            parse_mode="HTML"
        )
        await state.update_data(last_interface_id=msg.message_id)
    except TelegramBadRequest:
        await call.message.delete()
        msg = await call.message.answer(
            f"Меню {menu_title}:",
            reply_markup=kb_menu(role),
            parse_mode="HTML"
        )
        await state.update_data(last_interface_id=msg.message_id)


@router.callback_query(F.data == "menu_home")
async def back_to_menu_handler(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    """
    Повертає в меню поточної ролі.
    ВАЖЛИВО: Ця функція також чистить екран від чатів та списків.
    """
    data = await state.get_data()
    role = data.get("role", "passenger") # За замовчуванням пасажир
    
    # Збираємо ID для видалення
    ids_to_clean = []
    ids_to_clean.extend(data.get("trip_msg_ids", []))
    ids_to_clean.extend(data.get("booking_msg_ids", []))
    
    # Якщо користувач вийшов з чату через меню - чистимо чат
    delete_active_chat(call.from_user.id)
    ids_to_clean.extend(get_and_clear_chat_msgs(call.from_user.id))

    # Видаляємо все зайве, крім самого повідомлення з кнопкою (його ми відредагуємо)
    for msg_id in ids_to_clean:
        if msg_id != call.message.message_id:
            with suppress(TelegramBadRequest):
                await bot.delete_message(chat_id=call.message.chat.id, message_id=msg_id)

    # Скидаємо стан, але пам'ятаємо роль
    await state.clear()
    await state.update_data(role=role)
    
    menu_title = "Водія 🚖" if role == "driver" else "Пасажира 🚶"
    
    try:
        msg = await call.message.edit_text(
            f"Меню {menu_title}:",
            reply_markup=kb_menu(role),
            parse_mode="HTML"
        )
        await state.update_data(last_interface_id=msg.message_id)
    except Exception:
        with suppress(TelegramBadRequest):
            await call.message.delete()
        msg = await call.message.answer(
            f"Меню {menu_title}:",
            reply_markup=kb_menu(role),
            parse_mode="HTML"
        )
        await state.update_data(last_interface_id=msg.message_id)
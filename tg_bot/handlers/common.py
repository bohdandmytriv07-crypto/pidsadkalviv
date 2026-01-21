from contextlib import suppress
from aiogram import Router, F, types, Bot
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

# Імпорти з ваших файлів
from database import (
    is_user_banned, save_user, get_and_clear_chat_msgs, 
    delete_active_chat, get_user, 
    check_terms_status, accept_terms # 👈 Додані нові функції
)
from keyboards import kb_main_role, kb_menu
from utils import clean_user_input, update_or_send_msg, delete_prev_msg

router = Router()

# ==========================================
# 🚀 СТАРТ ТА ПЕРЕВІРКА ДОСТУПУ
# ==========================================

@router.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext, bot: Bot):
    # 1. Видаляємо саме повідомлення "/start" від користувача
    await clean_user_input(message)
    
    user_id = message.from_user.id
    
    # Зберігаємо юзера (оновлюємо ім'я, але не чіпаємо телефон, якщо він є)
    existing_user = get_user(user_id)
    current_phone = existing_user['phone'] if existing_user else "-"
    
    # Якщо юзера немає, save_user його створить. Якщо є - оновить ім'я.
    # Але terms_accepted ми тут не ставимо, це робить accept_terms
    if not existing_user:
        save_user(user_id, message.from_user.full_name, "-")
    
    # Перевірка бану
    if is_user_banned(user_id):
        await message.answer("⛔ <b>Ви заблоковані.</b>\nЗверніться до підтримки.", parse_mode="HTML")
        return

    # --- ГЕНЕРАЛЬНЕ ПРИБИРАННЯ (Чистимо старі повідомлення) ---
    await _clean_chat_interface(user_id, state, bot, message.chat.id)

    # --- ЛОГІКА ONBOARDING (Угода користувача) ---
    if check_terms_status(user_id):
        # ✅ Вже погодився -> Показуємо вибір ролі
        await _show_role_menu(message, state)
    else:
        # ❌ Ще не погодився -> Показуємо правила
        terms_text = (
            f"👋 <b>Вітаємо у спільноті «Підсадка Львів»!</b>\n\n"
            f"Перед початком роботи, будь ласка, уважно ознайомтесь з правилами сервісу.\n\n"
            
            f"📋 <b>Угода користувача:</b>\n\n"
            
            f"<b>1. Відмова від відповідальності</b>\n"
            f"Бот «Підсадка Львів» є виключно інформаційною платформою. Ми не є перевізником, службою таксі або роботодавцем водіїв. "
            f"Адміністрація не несе відповідальності за скасування поїздок, запізнення, стан авто або поведінку користувачів.\n\n"
            
            f"<b>2. Конфіденційність даних</b>\n"
            f"Натискаючи кнопку «Погоджуюсь», ви надаєте згоду на обробку ваших персональних даних (Ім'я, Telegram ID, Номер телефону). "
            f"Ваш номер телефону буде передано іншому користувачу (водію/пасажиру) <b>тільки у випадку успішного бронювання місця</b> для зв'язку.\n\n"
            
            f"<b>3. Безпека</b>\n"
            f"Ми рекомендуємо перевіряти дані співрозмовника перед поїздкою. Ви несете особисту відповідальність за свою безпеку під час подорожі.\n\n"
            
            f"<b>4. Принцип «Спільна поїздка»</b>\n"
            f"Сервіс працює за принципом компенсації витрат на пальне (ridesharing). Це не комерційна послуга перевезення.\n\n"
            
            f"<i>Натискаючи кнопку нижче, ви підтверджуєте, що вам виповнилося 18 років і ви приймаєте ці умови.</i>"
        )
        
        kb_terms = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Я погоджуюсь і приймаю умови", callback_data="terms_ok")]
        ])
        
        msg = await message.answer(terms_text, reply_markup=kb_terms, parse_mode="HTML")
        # Зберігаємо ID, щоб потім видалити це повідомлення
        await state.update_data(last_msg_id=msg.message_id)


# ==========================================
# ✅ ОБРОБКА ЗГОДИ
# ==========================================

@router.callback_query(F.data == "terms_ok")
async def terms_accepted_handler(call: types.CallbackQuery, state: FSMContext):
    # Записуємо в базу, що юзер погодився
    accept_terms(call.from_user.id, call.from_user.full_name)
    
    await call.answer("Дякую! Доступ відкрито ✅")
    
    # Видаляємо повідомлення з правилами (для чистоти)
    with suppress(TelegramBadRequest):
        await call.message.delete()
    
    # Показуємо меню
    await _show_role_menu(call.message, state)


# ==========================================
# 🛠 ДОПОМІЖНІ ФУНКЦІЇ
# ==========================================

async def _show_role_menu(message: types.Message, state: FSMContext):
    """Показує головне меню вибору ролі."""
    new_msg = await message.answer(
        "👋 <b>Вітаємо у pidsadkaLviv!</b>\nОберіть вашу роль:",
        reply_markup=kb_main_role(),
        parse_mode="HTML"
    )
    # Зберігаємо як last_msg_id, щоб update_or_send_msg міг його редагувати далі
    await state.update_data(last_msg_id=new_msg.message_id)


async def _clean_chat_interface(user_id: int, state: FSMContext, bot: Bot, chat_id: int):
    """Виконує повну очистку інтерфейсу від попередніх повідомлень."""
    data = await state.get_data()
    
    ids_to_delete = []
    if data.get("last_interface_id"): ids_to_delete.append(data.get("last_interface_id"))
    if data.get("last_msg_id"): ids_to_delete.append(data.get("last_msg_id"))
    ids_to_delete.extend(data.get("trip_msg_ids", []))
    ids_to_delete.extend(data.get("booking_msg_ids", []))
    ids_to_delete.extend(data.get("search_msg_ids", [])) # Не забуваємо про пошук
    
    delete_active_chat(user_id) 
    ids_to_delete.extend(get_and_clear_chat_msgs(user_id)) 

    for mid in ids_to_delete:
        if mid:
            with suppress(TelegramBadRequest):
                await bot.delete_message(chat_id=chat_id, message_id=mid)

    # Скидаємо стан
    await state.clear()


# ==========================================
# 🔄 НАВІГАЦІЯ (КНОПКИ "НАЗАД")
# ==========================================

@router.callback_query(F.data == "back_start")
async def back_to_start_handler(call: types.CallbackQuery, state: FSMContext):
    """Повернення до вибору ролі (Водій/Пасажир)."""
    prev_msg_id = call.message.message_id
    
    await state.clear()
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
    Повертає в меню і чистить ВСЕ сміття.
    """
    # Запам'ятовуємо ID кнопки, яку натиснули (щоб її не видалити, а відредагувати)
    prev_msg_id = call.message.message_id
    
    # Виконуємо очистку всього КРІМ поточного повідомлення
    # Тут ми вручну збираємо ID, бо _clean_chat_interface очищає і state, а нам треба зберегти prev_msg_id
    data = await state.get_data()
    role = data.get("role", "passenger")
    
    ids_to_clean = []
    ids_to_clean.extend(data.get("trip_msg_ids", []))
    ids_to_clean.extend(data.get("booking_msg_ids", []))
    ids_to_clean.extend(data.get("search_msg_ids", []))
    
    delete_active_chat(call.from_user.id)
    ids_to_clean.extend(get_and_clear_chat_msgs(call.from_user.id))

    for msg_id in ids_to_clean:
        if msg_id != prev_msg_id:
            with suppress(TelegramBadRequest):
                await bot.delete_message(chat_id=call.message.chat.id, message_id=msg_id)

    # Очищаємо стан, але відновлюємо роль і ID меню
    await state.clear()
    await state.update_data(role=role, last_msg_id=prev_msg_id)
    
    menu_title = "Водія 🚖" if role == "driver" else "Пасажира 🚶"
    
    # Редагуємо поточне повідомлення на Головне Меню
    await update_or_send_msg(
        bot, call.message.chat.id, state,
        f"Меню {menu_title}:",
        kb_menu(role)
    )


# ==========================================
# 🆘 ПІДТРИМКА
# ==========================================

@router.message(Command("support"))
async def cmd_support(message: types.Message):
    await message.answer(
        "🆘 <b>Підтримка</b>\n\n"
        "Знайшли помилку або є пропозиція?\n"
        "Напишіть розробнику: @admin_username", # Замініть на свій нік
        parse_mode="HTML"
    )
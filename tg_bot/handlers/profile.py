import re
from contextlib import suppress

from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

# Імпорти
from database import get_user, save_user
from states import ProfileStates
from keyboards import kb_back, kb_menu
from utils import clean_user_input, send_new_clean_msg, delete_prev_msg

router = Router()

# --- КОНСТАНТИ ---
CMD_ERROR_TEXT = "⛔ <b>Команди недоступні під час реєстрації!</b>\nБудь ласка, просто дайте відповідь на питання:"

# --- ДОПОМІЖНІ ФУНКЦІЇ ---

def kb_error_retry(callback_data: str) -> InlineKeyboardMarkup:
    """Генерує кнопку для повторної спроби при помилці."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Спробувати ще раз", callback_data=callback_data)]
    ])

async def _delete_message_safe(message: types.Message):
    """Безпечне видалення повідомлення."""
    with suppress(TelegramBadRequest):
        await message.delete()


# ==========================================
# 🔄 НАВІГАЦІЯ (КНОПКИ "НАЗАД")
# ==========================================

@router.callback_query(F.data == "back_to_menu")
async def back_to_menu_handler(call: types.CallbackQuery, state: FSMContext):
    await edit_profile_start(call, state)

@router.callback_query(F.data == "back_to_name")
async def back_to_name_handler(call: types.CallbackQuery, state: FSMContext):
    await start_profile_registration(call, state)

@router.callback_query(F.data == "back_to_phone")
async def back_to_phone_handler(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(ProfileStates.phone)
    await _delete_message_safe(call.message)
    
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Надіслати номер", request_contact=True)],
            [KeyboardButton(text="🚫 Не хочу вказувати")]
        ], 
        resize_keyboard=True, one_time_keyboard=True
    )
    msg = await call.message.answer(
        "📱 <b>Крок 2/5</b>\nНатисніть кнопку або введіть номер вручну:", 
        reply_markup=keyboard, 
        parse_mode="HTML"
    )
    await state.update_data(last_msg_id=msg.message_id)
    await call.answer()

@router.callback_query(F.data == "back_to_model")
async def back_to_model_handler(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(ProfileStates.model)
    await _delete_message_safe(call.message)
    
    msg = await call.message.answer(
        "🚘 <b>Крок 3/5</b>\nВведіть марку та модель авто:\n<i>(напр. BMW M5 F90)</i>", 
        reply_markup=ReplyKeyboardRemove(), 
        parse_mode="HTML"
    )
    await state.update_data(last_msg_id=msg.message_id)
    await call.answer()

@router.callback_query(F.data == "back_to_body")
async def back_to_body_handler(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(ProfileStates.body)
    await _delete_message_safe(call.message)
    
    msg = await call.message.answer(
        "🚜 <b>Крок 4/5</b>\nВведіть тип кузова:\n<i>(напр. Седан, Універсал)</i>", 
        parse_mode="HTML"
    )
    await state.update_data(last_msg_id=msg.message_id)
    await call.answer()

@router.callback_query(F.data == "back_to_color")
async def back_to_color_handler(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(ProfileStates.color)
    await _delete_message_safe(call.message)
    
    msg = await call.message.answer(
        "🎨 <b>Крок 5/5</b>\nВведіть колір авто:\n<i>(напр. Чорний, Білий)</i>", 
        parse_mode="HTML"
    )
    await state.update_data(last_msg_id=msg.message_id)
    await call.answer()

@router.callback_query(F.data == "back_to_number_choice")
async def back_to_number_choice_handler(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(ProfileStates.number)
    await _delete_message_safe(call.message)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇺🇦 Держ. номер (AA1234BB)", callback_data="numtype_standard")],
        [InlineKeyboardButton(text="😎 Іменний (до 12 симв.)", callback_data="numtype_named")]
    ])
    await call.message.answer("🔢 <b>Фінал</b>\nОберіть тип номерного знаку:", reply_markup=keyboard, parse_mode="HTML")
    await call.answer()

@router.callback_query(F.data == "back_to_number_input")
async def back_to_number_input_handler(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(ProfileStates.number)
    await _delete_message_safe(call.message)
    
    data = await state.get_data()
    num_type = data.get("number_type", "standard")
    
    if num_type == "standard":
        text = "🔢 <b>Введіть держ. номер:</b>\nФормат: 2 букви, 4 цифри, 2 букви\n<i>(напр. AA1234BB)</i>"
    else:
        text = "😎 <b>Введіть ваш номер:</b>\nДо 12 символів (літери, цифри, смайли)"
        
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Змінити тип", callback_data="back_to_number_choice")]])
    
    msg = await call.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    await state.update_data(last_msg_id=msg.message_id)
    await call.answer()


# ==========================================
# 👤 ПРОФІЛЬ ТА РЕЄСТРАЦІЯ
# ==========================================

@router.callback_query(F.data == "profile_edit")
async def edit_profile_start(call: types.CallbackQuery, state: FSMContext):
    """Показує поточний профіль користувача."""
    await _delete_message_safe(call.message)

    user = get_user(call.from_user.id)
    data = await state.get_data()
    role = data.get("role", "passenger") 

    if user:
        if role == "passenger":
            profile_text = (
                f"👤 <b>Ваш профіль:</b>\n\n"
                f"📛 Ім'я: <b>{user['name']}</b>\n"
                f"📱 Телефон: <code>{user['phone']}</code>"
            )
        else:
            profile_text = (
                f"🚖 <b>Ваш профіль водія:</b>\n\n"
                f"📛 Ім'я: {user['name']}\n"
                f"📱 Телефон: {user['phone']}\n"
                f"🚘 Авто: {user['model']} {user['color']}\n"
                f"🔢 Номер: <code>{user['number']}</code>\n"
                f"🚜 Кузов: {user['body']}"
            )

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Редагувати дані", callback_data="profile_new")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_home")]
        ])
        
        await call.message.answer(profile_text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await start_profile_registration(call, state)


# --- КРОК 1: ІМ'Я ---

@router.callback_query(F.data == "profile_new")
async def start_profile_registration(call: types.CallbackQuery, state: FSMContext):
    await _delete_message_safe(call.message)
    
    # Зберігаємо роль, очищаємо старі дані, відновлюємо роль
    data = await state.get_data()
    role = data.get("role", "passenger")
    
    await state.clear()
    await state.update_data(role=role)
    await state.set_state(ProfileStates.name)
    
    steps = "1/2" if role == "passenger" else "1/5"
    text = f"📝 <b>Крок {steps}</b>\nВведіть ваше ім'я та прізвище:\n<i>(напр. Іван)</i>"
    
    await send_new_clean_msg(call.message, state, text, kb_back())


@router.message(ProfileStates.name)
async def process_name(message: types.Message, state: FSMContext):
    await clean_user_input(message)
    
    if message.text and message.text.startswith("/"):
        await send_new_clean_msg(message, state, CMD_ERROR_TEXT, kb_error_retry("back_to_name"))
        return

    if not message.text or not re.match(r"^[A-Za-zА-Яа-яІіЇїЄєҐґ\s'-]+$", message.text):
        await send_new_clean_msg(
            message, state, 
            "❌ <b>Помилка!</b>\nІм'я не може містити цифри.\nСпробуйте ще раз:", 
            kb_error_retry("back_to_name")
        )
        return

    await state.update_data(name=message.text)
    
    await state.set_state(ProfileStates.phone)
    await delete_prev_msg(state, message.bot, message.chat.id)
    
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Надіслати номер", request_contact=True)],
            [KeyboardButton(text="🚫 Не хочу вказувати")]
        ], 
        resize_keyboard=True, one_time_keyboard=True
    )
    
    data = await state.get_data()
    steps = "2/2" if data.get("role") == "passenger" else "2/5"
    
    msg = await message.answer(
        f"📱 <b>Крок {steps}</b>\nНатисніть кнопку або введіть номер:", 
        reply_markup=keyboard, 
        parse_mode="HTML"
    )
    await state.update_data(last_msg_id=msg.message_id)


# --- КРОК 2: ТЕЛЕФОН ---

@router.message(ProfileStates.phone)
async def process_phone(message: types.Message, state: FSMContext):
    await _delete_message_safe(message)
    
    phone_to_save = None

    if message.contact:
        phone_to_save = re.sub(r'\D', '', message.contact.phone_number)
    
    elif message.text:
        text = message.text.strip()
        
        if text.startswith("/"):
            await delete_prev_msg(state, message.bot, message.chat.id)
            msg = await message.answer(CMD_ERROR_TEXT, reply_markup=kb_error_retry("back_to_phone"), parse_mode="HTML")
            await state.update_data(last_msg_id=msg.message_id)
            return

        if "не хочу" in text.lower():
             phone_to_save = "Не вказано"
        else:
            clean_phone = re.sub(r'\D', '', text)

            if len(clean_phone) == 10 and clean_phone.startswith('0'):
                clean_phone = '38' + clean_phone
            elif len(clean_phone) == 9: 
                clean_phone = '380' + clean_phone
            
            if re.match(r'^380\d{9}$', clean_phone):
                phone_to_save = clean_phone
            else:
                await delete_prev_msg(state, message.bot, message.chat.id)
                msg = await message.answer(
                    "❌ <b>Некоректний номер.</b>\n"
                    "Введіть український мобільний (0XX... або 380XX...)\nСпробуйте ще раз:", 
                    reply_markup=kb_error_retry("back_to_phone"), 
                    parse_mode="HTML"
                )
                await state.update_data(last_msg_id=msg.message_id)
                return
    else:
        await delete_prev_msg(state, message.bot, message.chat.id)
        msg = await message.answer(
            "❌ <b>Я очікую номер телефону.</b>", 
            reply_markup=kb_error_retry("back_to_phone"), 
            parse_mode="HTML"
        )
        await state.update_data(last_msg_id=msg.message_id)
        return

    await state.update_data(phone=phone_to_save)
    await delete_prev_msg(state, message.bot, message.chat.id)

    data = await state.get_data()
    
    if data.get("role") == "passenger":
        save_user(
            message.from_user.id, 
            data['name'], 
            phone_to_save, 
            "-", "-", "-", "-" 
        )
        await message.answer("✅ <b>Профіль збережено!</b>", reply_markup=kb_menu("passenger"), parse_mode="HTML")
        await state.clear()
        await state.update_data(role="passenger")
        
    else:
        await state.set_state(ProfileStates.model)
        txt = "🚘 <b>Крок 3/5</b>\nВведіть марку та модель авто:\n<i>(напр. BMW M5 F90)</i>"
        msg = await message.answer(txt, reply_markup=ReplyKeyboardRemove(), parse_mode="HTML")
        await state.update_data(last_msg_id=msg.message_id)


# --- КРОК 3: МОДЕЛЬ (Водій) ---

@router.message(ProfileStates.model)
async def process_model(message: types.Message, state: FSMContext):
    await clean_user_input(message)
    
    if message.text and message.text.startswith("/"):
        await send_new_clean_msg(message, state, CMD_ERROR_TEXT, kb_error_retry("back_to_model"))
        return

    if not message.text or len(message.text) < 2 or message.text.isdigit():
        await send_new_clean_msg(
            message, state, 
            "❌ <b>Занадто коротко.</b>\nВведіть повну назву авто:", 
            kb_error_retry("back_to_model")
        )
        return

    await state.update_data(model=message.text)
    await state.set_state(ProfileStates.body)
    await send_new_clean_msg(
        message, state, 
        "🚜 <b>Крок 4/5</b>\nВведіть тип кузова:\n<i>(напр. Седан, Універсал)</i>", 
        markup=None
    )


# --- КРОК 4: КУЗОВ (Водій) ---

@router.message(ProfileStates.body)
async def process_body(message: types.Message, state: FSMContext):
    await clean_user_input(message)
    
    if message.text and message.text.startswith("/"):
        await send_new_clean_msg(message, state, CMD_ERROR_TEXT, kb_error_retry("back_to_body"))
        return

    if not message.text or len(message.text) < 3 or re.search(r'\d', message.text):
        await send_new_clean_msg(
            message, state, 
            "❌ <b>Некоректний кузов.</b>\nВведіть словами (напр. Седан):", 
            kb_error_retry("back_to_body")
        )
        return

    await state.update_data(body=message.text)
    await state.set_state(ProfileStates.color)
    await send_new_clean_msg(
        message, state, 
        "🎨 <b>Крок 5/5</b>\nВведіть колір авто:\n<i>(напр. Чорний, Білий)</i>", 
        markup=None
    )


# --- КРОК 5: КОЛІР (Водій) ---

@router.message(ProfileStates.color)
async def process_color(message: types.Message, state: FSMContext):
    await clean_user_input(message)

    if message.text and message.text.startswith("/"):
        await send_new_clean_msg(message, state, CMD_ERROR_TEXT, kb_error_retry("back_to_color"))
        return
    
    if not message.text or len(message.text) < 3 or message.text.isdigit():
        await send_new_clean_msg(
            message, state, 
            "❌ <b>Вкажіть колір коректно.</b>\nНаприклад: 'Синій':", 
            kb_error_retry("back_to_color")
        )
        return

    await state.update_data(color=message.text)
    await state.set_state(ProfileStates.number) 
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇺🇦 Держ. номер (AA1234BB)", callback_data="numtype_standard")],
        [InlineKeyboardButton(text="😎 Іменний (до 12 симв.)", callback_data="numtype_named")]
    ])
    
    await send_new_clean_msg(message, state, "🔢 <b>Фінал</b>\nОберіть тип номерного знаку:", markup=keyboard)


# --- КРОК 6: ТИП НОМЕРА ---

@router.callback_query(F.data.startswith("numtype_"))
async def process_number_type(call: types.CallbackQuery, state: FSMContext):
    n_type = call.data.split("_")[1]
    await state.update_data(number_type=n_type)
    await _delete_message_safe(call.message)

    if n_type == "standard":
        text = "🔢 <b>Введіть держ. номер:</b>\nФормат: 2 букви, 4 цифри, 2 букви\n<i>(напр. AA1234BB)</i>"
    else:
        text = "😎 <b>Введіть ваш номер:</b>\nДо 12 символів (літери, цифри, смайли)"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Змінити тип", callback_data="back_to_number_choice")]])
    
    msg = await call.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    await state.update_data(last_msg_id=msg.message_id)
    await call.answer()


# --- КРОК 7: ВВЕДЕННЯ НОМЕРА (Фінал) ---

@router.message(ProfileStates.number)
async def process_number(message: types.Message, state: FSMContext):
    await clean_user_input(message)
    
    if message.text and message.text.startswith("/"):
        await send_new_clean_msg(message, state, CMD_ERROR_TEXT, kb_error_retry("back_to_number_input"))
        return

    data = await state.get_data()
    n_type = data.get("number_type", "standard") 
    
    raw_num = message.text.strip()
    clean_num = raw_num.upper()
    
    is_valid = False
    error_msg = ""

    if n_type == "standard":
        clean_num = clean_num.replace(" ", "").replace("-", "")
        
        translation = str.maketrans("АВЕКМНОРСТУХІ", "ABEKMHOPCTYXI")
        clean_num = clean_num.translate(translation)

        if re.match(r"^[A-Z]{2}\d{4}[A-Z]{2}$", clean_num):
            is_valid = True
        else:
            error_msg = "❌ <b>Невірний формат або мова.</b>\nВикористовуйте тільки латинські літери (English) та цифри.\nПриклад: AA1234BB"

    else:
        if 1 <= len(raw_num) <= 12:
            is_valid = True
            clean_num = raw_num 
        else:
            error_msg = "❌ <b>Занадто довгий номер.</b>\nМаксимум 12 символів."

    if not is_valid:
        await send_new_clean_msg(
            message, state, 
            f"{error_msg}\nСпробуйте ще раз:", 
            kb_error_retry("back_to_number_input")
        )
        return

    # ЗБЕРЕЖЕННЯ ПРОФІЛЮ ВОДІЯ
    await delete_prev_msg(state, message.bot, message.chat.id)

    save_user(
        message.from_user.id, 
        data['name'], 
        data['phone'], 
        data['model'], 
        data['body'], 
        data['color'], 
        clean_num
    )
    
    await message.answer("✅ <b>Водій готовий!</b>", reply_markup=kb_menu("driver"), parse_mode="HTML")
    await state.clear()
    await state.update_data(role="driver")


# ==========================================
# 🚘 ДОДАВАННЯ АВТО (ШВИДКИЙ ВХІД)
# ==========================================

@router.callback_query(F.data == "profile_add_car")
async def add_car_details_start(call: types.CallbackQuery, state: FSMContext):
    """Швидкий перехід до додавання авто, якщо ім'я та телефон вже є."""
    await _delete_message_safe(call.message)
    
    user = get_user(call.from_user.id)
    
    if not user:
        await start_profile_registration(call, state)
        return

    await state.clear()
    await state.update_data(
        role="driver",        
        name=user['name'],    
        phone=user['phone']   
    )
    
    await state.set_state(ProfileStates.model)
    
    msg = await call.message.answer(
        "🚘 <b>Додавання авто</b>\nВведіть марку та модель авто:\n<i>(напр. Skoda Octavia)</i>", 
        reply_markup=ReplyKeyboardRemove(), 
        parse_mode="HTML"
    )
    await state.update_data(last_msg_id=msg.message_id)
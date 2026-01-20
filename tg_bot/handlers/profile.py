import re
from contextlib import suppress
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

from database import get_user, save_user
from states import ProfileStates
from keyboards import kb_back, kb_menu, kb_car_type # 👈 Нова клавіатура
from utils import clean_user_input, send_new_clean_msg, delete_prev_msg, update_or_send_msg

router = Router()

CMD_ERROR_TEXT = "⛔ <b>Команди недоступні під час реєстрації!</b>\nБудь ласка, просто дайте відповідь на питання:"

def kb_error_retry(callback_data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Спробувати ще раз", callback_data=callback_data)]
    ])

async def _delete_message_safe(message: types.Message):
    with suppress(TelegramBadRequest):
        await message.delete()


# ==========================================
# 🔄 НАВІГАЦІЯ
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
    await delete_prev_msg(state, call.bot, call.message.chat.id)
    
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Надіслати номер", request_contact=True)],
            [KeyboardButton(text="🚫 Не хочу вказувати")]
        ], 
        resize_keyboard=True, one_time_keyboard=True
    )
    await send_new_clean_msg(call.message, state, "📱 <b>Крок 2/5</b>\nНатисніть кнопку або введіть номер:", keyboard)
    await call.answer()

@router.callback_query(F.data == "back_to_model")
async def back_to_model_handler(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(ProfileStates.model)
    await update_or_send_msg(
        call.bot, call.message.chat.id, state,
        "🚘 <b>Крок 3/5</b>\nВведіть марку та модель авто:\n<i>(напр. BMW M5 F90)</i>",
        kb_back()
    )
    await call.answer()

@router.callback_query(F.data == "back_to_body")
async def back_to_body_handler(call: types.CallbackQuery, state: FSMContext):
    # Повертаємося до вибору типу кузова (КНОПКИ)
    await state.set_state(ProfileStates.body)
    await update_or_send_msg(
        call.bot, call.message.chat.id, state,
        "🚙 <b>Крок 4/5</b>\nОберіть тип авто:",
        kb_car_type()
    )
    await call.answer()

@router.callback_query(F.data == "back_to_color")
async def back_to_color_handler(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(ProfileStates.color)
    await update_or_send_msg(
        call.bot, call.message.chat.id, state,
        "🎨 <b>Крок 5/5</b>\nВведіть колір авто:\n<i>(напр. Чорний, Білий)</i>",
        kb_back()
    )
    await call.answer()

@router.callback_query(F.data == "back_to_number_choice")
async def back_to_number_choice_handler(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(ProfileStates.number)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇺🇦 Держ. номер (AA1234BB)", callback_data="numtype_standard")],
        [InlineKeyboardButton(text="😎 Іменний (до 12 симв.)", callback_data="numtype_named")]
    ])
    await update_or_send_msg(call.bot, call.message.chat.id, state, "🔢 <b>Фінал</b>\nОберіть тип номерного знаку:", keyboard)
    await call.answer()

@router.callback_query(F.data == "back_to_number_input")
async def back_to_number_input_handler(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(ProfileStates.number)
    data = await state.get_data()
    num_type = data.get("number_type", "standard")
    
    if num_type == "standard":
        text = "🔢 <b>Введіть держ. номер:</b>\nФормат: 2 букви, 4 цифри, 2 букви\n<i>(напр. AA1234BB)</i>"
    else:
        text = "😎 <b>Введіть ваш номер:</b>\nДо 12 символів (літери, цифри, смайли)"
        
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Змінити тип", callback_data="back_to_number_choice")]])
    await update_or_send_msg(call.bot, call.message.chat.id, state, text, keyboard)
    await call.answer()


# ==========================================
# 👤 ПРОФІЛЬ ТА РЕЄСТРАЦІЯ
# ==========================================

@router.callback_query(F.data == "profile_edit")
async def edit_profile_start(call: types.CallbackQuery, state: FSMContext):
    """Показує поточний профіль користувача."""
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
                f"🚙 Тип: {user['body']}"
            )

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Редагувати дані", callback_data="profile_new")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_home")]
        ])
        
        try:
            await call.message.edit_text(profile_text, reply_markup=keyboard, parse_mode="HTML")
            await state.update_data(last_msg_id=call.message.message_id)
        except:
            await _delete_message_safe(call.message)
            msg = await call.message.answer(profile_text, reply_markup=keyboard, parse_mode="HTML")
            await state.update_data(last_msg_id=msg.message_id)
    else:
        await start_profile_registration(call, state)


# --- КРОК 1: ІМ'Я ---

@router.callback_query(F.data == "profile_new")
async def start_profile_registration(call: types.CallbackQuery, state: FSMContext):
    prev_id = call.message.message_id
    data = await state.get_data()
    role = data.get("role", "passenger")
    
    await state.clear()
    await state.update_data(role=role, last_msg_id=prev_id)
    await state.set_state(ProfileStates.name)
    
    steps = "1/2" if role == "passenger" else "1/5"
    text = f"📝 <b>Крок {steps}</b>\nВведіть ваше ім'я та прізвище:\n<i>(напр. Іван Петренко)</i>"
    
    await update_or_send_msg(call.bot, call.message.chat.id, state, text, kb_back())


@router.message(ProfileStates.name)
async def process_name(message: types.Message, state: FSMContext):
    await clean_user_input(message)
    
    if message.text and message.text.startswith("/"):
        await update_or_send_msg(
            message.bot, message.chat.id, state, 
            CMD_ERROR_TEXT, kb_error_retry("back_to_name")
        )
        return

    if not message.text or not re.match(r"^[A-Za-zА-Яа-яІіЇїЄєҐґ\s'-]+$", message.text):
        await update_or_send_msg(
            message.bot, message.chat.id, state, 
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
    
    await send_new_clean_msg(
        message, state, 
        f"📱 <b>Крок {steps}</b>\nНатисніть кнопку або введіть номер:", 
        keyboard
    )


# --- КРОК 2: ТЕЛЕФОН ---

@router.message(ProfileStates.phone)
async def process_phone(message: types.Message, state: FSMContext):
    with suppress(TelegramBadRequest): await message.delete()
    
    phone_to_save = None

    if message.contact:
        phone_to_save = re.sub(r'\D', '', message.contact.phone_number)
    
    elif message.text:
        text = message.text.strip()
        
        if text.startswith("/"):
            await update_or_send_msg(message.bot, message.chat.id, state, CMD_ERROR_TEXT, kb_error_retry("back_to_phone"))
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
                await send_new_clean_msg(
                    message, state, 
                    "❌ <b>Некоректний номер.</b>\nВведіть український мобільний (0XX...)\nСпробуйте ще раз:", 
                    kb_error_retry("back_to_phone")
                )
                return
    else:
        await send_new_clean_msg(
            message, state, 
            "❌ <b>Я очікую номер телефону.</b>", 
            kb_error_retry("back_to_phone")
        )
        return

    await state.update_data(phone=phone_to_save)
    await delete_prev_msg(state, message.bot, message.chat.id)

    data = await state.get_data()
    
    if data.get("role") == "passenger":
        save_user(message.from_user.id, data['name'], phone_to_save, "-", "-", "-", "-")
        
        msg = await message.answer("✅ <b>Профіль збережено!</b>", reply_markup=kb_menu("passenger"), parse_mode="HTML")
        await state.update_data(last_interface_id=msg.message_id)
        await state.clear()
        await state.update_data(role="passenger")
    else:
        await state.set_state(ProfileStates.model)
        await send_new_clean_msg(
            message, state, 
            "🚘 <b>Крок 3/5</b>\nВведіть марку та модель авто:\n<i>(напр. BMW X5)</i>", 
            kb_back()
        )


# --- КРОК 3: МОДЕЛЬ (Водій) ---

@router.message(ProfileStates.model)
async def process_model(message: types.Message, state: FSMContext):
    await clean_user_input(message)
    
    if message.text and message.text.startswith("/"):
        await update_or_send_msg(message.bot, message.chat.id, state, CMD_ERROR_TEXT, kb_error_retry("back_to_model"))
        return

    if not message.text or len(message.text) < 2 or message.text.isdigit():
        await update_or_send_msg(
            message.bot, message.chat.id, state, 
            "❌ <b>Занадто коротко.</b>\nВведіть повну назву авто:", 
            kb_error_retry("back_to_model")
        )
        return

    await state.update_data(model=message.text)
    
    # 🔥 ПЕРЕХІД ДО ТИПУ КУЗОВА (КНОПКИ)
    await state.set_state(ProfileStates.body)
    await update_or_send_msg(
        message.bot, message.chat.id, state,
        "🚙 <b>Крок 4/5</b>\nОберіть тип авто:", 
        kb_car_type() # 👈 Тут показуємо нові кнопки
    )


# --- КРОК 4: КУЗОВ (Водій) - ОБРОБКА КНОПОК ---

@router.callback_query(ProfileStates.body, F.data.startswith("body_"))
async def process_body_buttons(call: types.CallbackQuery, state: FSMContext):
    selected_type = "Легкова" if call.data == "body_car" else "Бус"
    
    await state.update_data(body=selected_type)
    
    # Перехід до кольору
    await state.set_state(ProfileStates.color)
    await update_or_send_msg(
        call.bot, call.message.chat.id, state,
        f"✅ Тип: <b>{selected_type}</b>\n\n🎨 <b>Крок 5/5</b>\nВведіть колір авто:\n<i>(напр. Чорний, Білий)</i>",
        kb_back() # Кнопка назад тепер поверне до вибору типу
    )


# --- КРОК 5: КОЛІР (Водій) ---

@router.message(ProfileStates.color)
async def process_color(message: types.Message, state: FSMContext):
    await clean_user_input(message)

    if message.text and message.text.startswith("/"):
        await update_or_send_msg(message.bot, message.chat.id, state, CMD_ERROR_TEXT, kb_error_retry("back_to_color"))
        return
    
    if not message.text or len(message.text) < 3 or message.text.isdigit():
        await update_or_send_msg(
            message.bot, message.chat.id, state, 
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
    
    await update_or_send_msg(
        message.bot, message.chat.id, state, 
        "🔢 <b>Фінал</b>\nОберіть тип номерного знаку:", 
        keyboard
    )


# --- КРОК 6: ТИП НОМЕРА ---

@router.callback_query(F.data.startswith("numtype_"))
async def process_number_type(call: types.CallbackQuery, state: FSMContext):
    n_type = call.data.split("_")[1]
    await state.update_data(number_type=n_type)
    
    if n_type == "standard":
        text = "🔢 <b>Введіть держ. номер:</b>\nФормат: 2 букви, 4 цифри, 2 букви\n<i>(напр. AA1234BB)</i>"
    else:
        text = "😎 <b>Введіть ваш номер:</b>\nДо 12 символів (літери, цифри, смайли)"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Змінити тип", callback_data="back_to_number_choice")]])
    
    await update_or_send_msg(call.bot, call.message.chat.id, state, text, keyboard)
    await call.answer()


# --- КРОК 7: ВВЕДЕННЯ НОМЕРА (Фінал) ---

@router.message(ProfileStates.number)
async def process_number(message: types.Message, state: FSMContext):
    await clean_user_input(message)
    
    if message.text and message.text.startswith("/"):
        await update_or_send_msg(message.bot, message.chat.id, state, CMD_ERROR_TEXT, kb_error_retry("back_to_number_input"))
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
        await update_or_send_msg(
            message.bot, message.chat.id, state, 
            f"{error_msg}\nСпробуйте ще раз:", 
            kb_error_retry("back_to_number_input")
        )
        return

    # ЗБЕРЕЖЕННЯ ПРОФІЛЮ ВОДІЯ
    await delete_prev_msg(state, message.bot, message.chat.id)

    save_user(
        message.from_user.id, 
        data['name'], data['phone'], 
        data['model'], data['body'], 
        data['color'], clean_num
    )
    
    msg = await message.answer("✅ <b>Водій готовий!</b>", reply_markup=kb_menu("driver"), parse_mode="HTML")
    await state.clear()
    await state.update_data(role="driver", last_interface_id=msg.message_id)


# ==========================================
# 🚘 ДОДАВАННЯ АВТО (ШВИДКИЙ ВХІД)
# ==========================================

@router.callback_query(F.data == "profile_add_car")
async def add_car_details_start(call: types.CallbackQuery, state: FSMContext):
    prev_id = call.message.message_id
    
    user = get_user(call.from_user.id)
    if not user:
        await start_profile_registration(call, state)
        return

    await state.clear()
    await state.update_data(
        role="driver",        
        name=user['name'],    
        phone=user['phone'],
        last_msg_id=prev_id 
    )
    
    await state.set_state(ProfileStates.model)
    
    await update_or_send_msg(
        call.bot, call.message.chat.id, state,
        "🚘 <b>Додавання авто</b>\nВведіть марку та модель авто:\n<i>(напр. Skoda Octavia)</i>", 
        kb_back()
    )
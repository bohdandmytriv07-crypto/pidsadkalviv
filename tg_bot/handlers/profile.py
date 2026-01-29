import re
from contextlib import suppress
from aiogram import Router, F, types, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from database import get_user, save_user, get_user_rating, format_rating
from states import ProfileStates
from keyboards import kb_back, kb_menu, kb_car_type, kb_plate_type
# 🔥 ДОДАНО: delete_prev_msg для очистки
from utils import clean_user_input, send_new_clean_msg, update_or_send_msg, delete_prev_msg

router = Router()

@router.callback_query(F.data == "profile_edit")
async def show_profile(call: types.CallbackQuery, state: FSMContext):
    user = get_user(call.from_user.id)
    data = await state.get_data()
    role = data.get("role", "passenger")
    
    if user and user['phone'] != "-":
        avg, count = get_user_rating(call.from_user.id)
        if role == "passenger":
            txt = f"👤 <b>Ваш профіль:</b>\n\n📛 {user['name']}\n📱 {user['phone']}\n{format_rating(avg, count)}"
        else:
            txt = f"🚖 <b>Профіль водія:</b>\n\n📛 {user['name']}\n📱 {user['phone']}\n🚘 {user['model']} {user['color']}\n🔢 {user['number']}\n{format_rating(avg, count)}"
            
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Редагувати", callback_data="profile_new")],
            [InlineKeyboardButton(text="🔙 В меню", callback_data="menu_home")]
        ])
        await update_or_send_msg(call.bot, call.message.chat.id, state, txt, kb)
    else:
        await start_reg(call, state)

@router.callback_query(F.data == "profile_new")
async def start_reg(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(ProfileStates.name)
    await update_or_send_msg(call.bot, call.message.chat.id, state, "📝 <b>Як вас звати?</b>\nВведіть ім'я та прізвище:", kb_back())

@router.message(ProfileStates.name)
async def process_name(message: types.Message, state: FSMContext):
    await clean_user_input(message)
    if len(message.text) < 2: return 
    
    # 🔥 Видаляємо питання "Як вас звати?"
    await delete_prev_msg(state, message.bot, message.chat.id)
    
    await state.update_data(name=message.text)
    await state.set_state(ProfileStates.phone)
    
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Надіслати номер", request_contact=True)]], 
        resize_keyboard=True, 
        one_time_keyboard=True
    )
    # Зберігаємо ID цього повідомлення, щоб видалити його потім
    msg = await message.answer("📱 <b>Ваш номер телефону:</b>\nНатисніть кнопку або введіть (можна з дужками/пробілами):", reply_markup=kb, parse_mode="HTML")
    await state.update_data(last_msg_id=msg.message_id)

@router.message(ProfileStates.phone)
async def process_phone(message: types.Message, state: FSMContext):
    # Очищаємо інтерфейс ("Зберігаю..." і клавіатуру)
    rm_msg = await message.answer("⏳ Перевіряю...", reply_markup=ReplyKeyboardRemove())
    with suppress(Exception): await message.delete()
    
    raw_phone = message.contact.phone_number if message.contact else message.text
    clean_digits = re.sub(r'\D', '', raw_phone) 
    
    if len(clean_digits) == 10 and clean_digits.startswith('0'):
        clean_digits = '38' + clean_digits
    elif len(clean_digits) == 11 and clean_digits.startswith('80'):
        clean_digits = '3' + clean_digits
    
    if len(clean_digits) != 12 or not clean_digits.startswith('380'):
        with suppress(Exception): await rm_msg.delete()
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Надіслати номер", request_contact=True)]], resize_keyboard=True, one_time_keyboard=True)
        # Оновлюємо ID повідомлення, якщо помилка
        msg = await message.answer("❌ <b>Невірний формат номера!</b>\nПотрібен український мобільний (напр. 066 123 45 67).", reply_markup=kb, parse_mode="HTML")
        await state.update_data(last_msg_id=msg.message_id)
        return

    final_phone = f"+{clean_digits}"
    await state.update_data(phone=final_phone)
    data = await state.get_data()
    
    with suppress(Exception): await rm_msg.delete()
    # 🔥 Видаляємо старе питання "Введіть номер"
    await delete_prev_msg(state, message.bot, message.chat.id)

    if data.get("role") == "passenger":
        uname = f"@{message.from_user.username}" if message.from_user.username else None
        save_user(message.from_user.id, data['name'], uname, final_phone)
        await state.clear()
        await state.update_data(role="passenger")
        msg = await message.answer("✅ <b>Профіль збережено!</b>", reply_markup=kb_menu("passenger"), parse_mode="HTML")
        await state.update_data(last_msg_id=msg.message_id)
    else:
        await state.set_state(ProfileStates.model)
        await send_new_clean_msg(message, state, "🚘 <b>Марка та модель авто:</b>\nНаприклад: Skoda Octavia", kb_back())

@router.message(ProfileStates.model)
async def process_model(message: types.Message, state: FSMContext):
    await clean_user_input(message)
    if len(message.text) < 2 or len(message.text) > 30:
        await update_or_send_msg(message.bot, message.chat.id, state, "⚠️ Назва авто має бути від 2 до 30 символів.", kb_back())
        return
    
    # 🔥 Видаляємо питання про модель
    await delete_prev_msg(state, message.bot, message.chat.id)
        
    await state.update_data(model=message.text)
    await state.set_state(ProfileStates.body)
    await update_or_send_msg(message.bot, message.chat.id, state, "🚙 <b>Тип кузова:</b>", kb_car_type())

@router.callback_query(ProfileStates.body)
async def process_body(call: types.CallbackQuery, state: FSMContext):
    # Тут update_or_send_msg сам замінить попереднє повідомлення, бо це Callback
    body = "Легкова" if call.data == "body_car" else "Бус"
    await state.update_data(body=body)
    await state.set_state(ProfileStates.color)
    await update_or_send_msg(call.bot, call.message.chat.id, state, "🎨 <b>Колір авто:</b>\n(Напр. Чорний, Білий, Червоний)", kb_back())

@router.message(ProfileStates.color)
async def process_color(message: types.Message, state: FSMContext):
    await clean_user_input(message)
    # 🔥 Видаляємо питання про колір
    await delete_prev_msg(state, message.bot, message.chat.id)
    
    await state.update_data(color=message.text)
    await update_or_send_msg(message.bot, message.chat.id, state, "🔢 <b>Який у вас номерний знак?</b>", kb_plate_type())

@router.callback_query(F.data.startswith("plate_type_"))
async def process_plate_type(call: types.CallbackQuery, state: FSMContext):
    p_type = call.data.split("_")[2]
    await state.update_data(plate_type=p_type)
    await state.set_state(ProfileStates.number)
    
    if p_type == "std":
        text = "🔢 <b>Введіть держ. номер:</b>\nФормат: <code>AA1234AA</code> (Можна вводити з пробілами, маленькими літерами — я виправлю)"
    else:
        text = "😎 <b>Введіть іменний номер:</b>\nВід 3 до 8 символів (тільки літери та цифри)."
        
    await update_or_send_msg(call.bot, call.message.chat.id, state, text, kb_back())

@router.message(ProfileStates.number)
async def process_number(message: types.Message, state: FSMContext, bot: Bot):
    await clean_user_input(message)
    data = await state.get_data()
    plate_type = data.get("plate_type", "std")
    
    raw_num = message.text.strip().upper().replace(" ", "").replace("-", "")
    translation = str.maketrans("АВЕКМНОРСТІХ", "ABEKMHOPCTIX") 
    clean_num = raw_num.translate(translation)

    error_msg = None
    if plate_type == "std":
        if not re.match(r'^[A-ZА-ЯІ]{2}\d{4}[A-ZА-ЯІ]{2}$', clean_num):
            error_msg = "❌ <b>Невірний формат!</b>\nПотрібно: 2 букви, 4 цифри, 2 букви.\nПриклад: <code>BC1234AI</code>"
    else:
        if len(clean_num) < 3 or len(clean_num) > 8:
            error_msg = "❌ <b>Невірна довжина!</b>\nІменний номер має бути від 3 до 8 символів."
        elif not re.match(r'^[A-ZА-ЯІ0-9]+$', clean_num):
            error_msg = "❌ <b>Тільки літери та цифри!</b>\nБез спецсимволів."

    if error_msg:
        await update_or_send_msg(bot, message.chat.id, state, error_msg, kb_back())
        return

    # 🔥 Видаляємо питання про номер
    await delete_prev_msg(state, bot, message.chat.id)

    uname = f"@{message.from_user.username}" if message.from_user.username else None
    
    save_user(
        message.from_user.id, data['name'], uname, 
        data['phone'], data['model'], data['body'], 
        data['color'], clean_num
    )
    
    await state.clear()
    await state.update_data(role="driver")
    
    kb = kb_menu("driver")
    # Відправляємо фінальне повідомлення
    msg = await message.answer(f"✅ <b>Водій готовий!</b>\nНомер: <code>{clean_num}</code>", reply_markup=kb, parse_mode="HTML")
    await state.update_data(last_msg_id=msg.message_id)
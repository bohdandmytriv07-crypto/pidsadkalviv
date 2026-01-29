import re
from contextlib import suppress
from aiogram import Router, F, types, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from database import get_user, save_user, get_user_rating, format_rating
from states import ProfileStates
from keyboards import kb_back, kb_menu, kb_car_type, kb_plate_type
from utils import clean_user_input, send_new_clean_msg, update_or_send_msg, delete_prev_msg

router = Router()

@router.callback_query(F.data == "profile_edit")
async def show_profile(call: types.CallbackQuery, state: FSMContext):
    user = get_user(call.from_user.id)
    data = await state.get_data()
    # Якщо роль не задана в стані, беремо з бази (якщо є авто -> водій)
    role = data.get("role")
    if not role:
        role = "driver" if user and user['model'] != "-" else "passenger"
        await state.update_data(role=role)
    
    if user and user['phone'] != "-":
        avg, count = get_user_rating(call.from_user.id)
        
        # 🔥 РОЗДІЛЕНІ КНОПКИ РЕДАГУВАННЯ
        if role == "passenger":
            txt = f"👤 <b>Ваш профіль:</b>\n\n📛 {user['name']}\n📱 {user['phone']}\n{format_rating(avg, count)}"
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✏️ Змінити ім'я та телефон", callback_data="edit_personal")],
                [InlineKeyboardButton(text="🔙 В меню", callback_data="menu_home")]
            ])
        else:
            txt = f"🚖 <b>Профіль водія:</b>\n\n📛 {user['name']}\n📱 {user['phone']}\n🚘 {user['model']} {user['color']}\n🔢 {user['number']}\n{format_rating(avg, count)}"
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✏️ Змінити ім'я/телефон", callback_data="edit_personal")],
                [InlineKeyboardButton(text="🚘 Змінити авто", callback_data="edit_car")],
                [InlineKeyboardButton(text="🔙 В меню", callback_data="menu_home")]
            ])
            
        await update_or_send_msg(call.bot, call.message.chat.id, state, txt, kb)
    else:
        # Якщо профілю немає - повна реєстрація
        await start_full_reg(call, state)

# ==========================================
# 🏁 ТОЧКИ ВХОДУ (Старт редагування)
# ==========================================

@router.callback_query(F.data == "profile_new")
async def start_full_reg(call: types.CallbackQuery, state: FSMContext):
    """Повна реєстрація з нуля"""
    await state.update_data(edit_mode="full") # Помічаємо, що це повний цикл
    await state.set_state(ProfileStates.name)
    await update_or_send_msg(call.bot, call.message.chat.id, state, "📝 <b>Як вас звати?</b>\nВведіть ім'я та прізвище:", kb_back())

@router.callback_query(F.data == "edit_personal")
async def start_edit_personal(call: types.CallbackQuery, state: FSMContext):
    """Тільки особисті дані"""
    await state.update_data(edit_mode="personal") # Тільки ім'я/тел
    await state.set_state(ProfileStates.name)
    await update_or_send_msg(call.bot, call.message.chat.id, state, "📝 <b>Введіть нове ім'я:</b>", kb_back())

@router.callback_query(F.data == "edit_car")
async def start_edit_car(call: types.CallbackQuery, state: FSMContext):
    """Тільки авто"""
    await state.update_data(edit_mode="car") # Тільки машина
    await state.set_state(ProfileStates.model)
    await update_or_send_msg(call.bot, call.message.chat.id, state, "🚘 <b>Введіть нову марку та модель:</b>", kb_back())

# ==========================================
# 👤 ОСОБИСТІ ДАНІ
# ==========================================

@router.message(ProfileStates.name)
async def process_name(message: types.Message, state: FSMContext):
    await clean_user_input(message)
    if len(message.text) < 2: return 
    await delete_prev_msg(state, message.bot, message.chat.id)
    
    await state.update_data(name=message.text)
    await state.set_state(ProfileStates.phone)
    
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Надіслати номер", request_contact=True)]], 
        resize_keyboard=True, one_time_keyboard=True
    )
    msg = await message.answer("📱 <b>Ваш номер телефону:</b>\nНатисніть кнопку або введіть:", reply_markup=kb, parse_mode="HTML")
    await state.update_data(last_msg_id=msg.message_id)

@router.message(ProfileStates.phone)
async def process_phone(message: types.Message, state: FSMContext):
    if message.contact and message.contact.user_id != message.from_user.id:
        await message.answer("⛔ <b>Це не ваш контакт!</b>\nНатисніть кнопку внизу або введіть номер вручну.")
        return
    rm_msg = await message.answer("⏳ Зберігаю...", reply_markup=ReplyKeyboardRemove())
    with suppress(Exception): await message.delete()
    
    raw_phone = message.contact.phone_number if message.contact else message.text
    clean_digits = re.sub(r'\D', '', raw_phone) 
    
    if len(clean_digits) == 10 and clean_digits.startswith('0'): clean_digits = '38' + clean_digits
    elif len(clean_digits) == 11 and clean_digits.startswith('80'): clean_digits = '3' + clean_digits
    
    if len(clean_digits) != 12 or not clean_digits.startswith('380'):
        with suppress(Exception): await rm_msg.delete()
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Надіслати номер", request_contact=True)]], resize_keyboard=True, one_time_keyboard=True)
        msg = await message.answer("❌ <b>Невірний формат!</b>\nПотрібен: +380...", reply_markup=kb, parse_mode="HTML")
        await state.update_data(last_msg_id=msg.message_id)
        return

    final_phone = f"+{clean_digits}"
    await state.update_data(phone=final_phone)
    with suppress(Exception): await rm_msg.delete()
    await delete_prev_msg(state, message.bot, message.chat.id)

    # 🔥 ЛОГІКА РОЗГАЛУЖЕННЯ
    data = await state.get_data()
    edit_mode = data.get("edit_mode")
    role = data.get("role", "passenger")

    # Якщо ми редагуємо ТІЛЬКИ особисті дані АБО це пасажир -> зберігаємо і виходимо
    if edit_mode == "personal" or role == "passenger":
        uname = f"@{message.from_user.username}" if message.from_user.username else None
        # Зберігаємо (поля авто не чіпаємо, бо вони дефолтні '-' і база їх проігнорує при update)
        save_user(message.from_user.id, data['name'], uname, final_phone)
        
        await state.clear()
        # Відновлюємо роль
        await state.update_data(role=role)
        
        kb = kb_menu(role)
        msg = await message.answer("✅ <b>Особисті дані оновлено!</b>", reply_markup=kb, parse_mode="HTML")
        await state.update_data(last_msg_id=msg.message_id)
    else:
        # Якщо це повна реєстрація водія -> йдемо далі до машини
        await state.set_state(ProfileStates.model)
        await send_new_clean_msg(message, state, "🚘 <b>Марка та модель авто:</b>", kb_back())

# ==========================================
# 🚘 ДАНІ АВТОМОБІЛЯ
# ==========================================

@router.message(ProfileStates.model)
async def process_model(message: types.Message, state: FSMContext):
    await clean_user_input(message)
    if len(message.text) < 2 or len(message.text) > 30:
        await update_or_send_msg(message.bot, message.chat.id, state, "⚠️ Назва від 2 до 30 символів.", kb_back())
        return
    
    await delete_prev_msg(state, message.bot, message.chat.id)
    await state.update_data(model=message.text)
    await state.set_state(ProfileStates.body)
    await update_or_send_msg(message.bot, message.chat.id, state, "🚙 <b>Тип кузова:</b>", kb_car_type())

@router.callback_query(ProfileStates.body)
async def process_body(call: types.CallbackQuery, state: FSMContext):
    body = "Легкова" if call.data == "body_car" else "Бус"
    await state.update_data(body=body)
    await state.set_state(ProfileStates.color)
    await update_or_send_msg(call.bot, call.message.chat.id, state, "🎨 <b>Колір авто:</b>", kb_back())

@router.message(ProfileStates.color)
async def process_color(message: types.Message, state: FSMContext):
    await clean_user_input(message)
    await delete_prev_msg(state, message.bot, message.chat.id)
    await state.update_data(color=message.text)
    await update_or_send_msg(message.bot, message.chat.id, state, "🔢 <b>Який у вас номерний знак?</b>", kb_plate_type())

@router.callback_query(F.data.startswith("plate_type_"))
async def process_plate_type(call: types.CallbackQuery, state: FSMContext):
    p_type = call.data.split("_")[2]
    await state.update_data(plate_type=p_type)
    await state.set_state(ProfileStates.number)
    
    if p_type == "std":
        text = "🔢 <b>Введіть держ. номер:</b>\nФормат: <code>AA1234AA</code>"
    else:
        text = "😎 <b>Введіть іменний номер:</b>\nТільки літери/цифри (3-8 симв)."
    await update_or_send_msg(call.bot, call.message.chat.id, state, text, kb_back())

@router.message(ProfileStates.number)
async def process_number(message: types.Message, state: FSMContext, bot: Bot):
    await clean_user_input(message)
    data = await state.get_data()
    
    raw_num = message.text.strip().upper().replace(" ", "").replace("-", "")
    translation = str.maketrans("АВЕКМНОРСТІХ", "ABEKMHOPCTIX") 
    clean_num = raw_num.translate(translation)

    error_msg = None
    if data.get("plate_type") == "std":
        if not re.match(r'^[A-ZА-ЯІ]{2}\d{4}[A-ZА-ЯІ]{2}$', clean_num):
            error_msg = "❌ <b>Невірний формат!</b> Приклад: BC1234AI"
    else:
        if len(clean_num) < 3 or len(clean_num) > 8 or not re.match(r'^[A-ZА-ЯІ0-9]+$', clean_num):
            error_msg = "❌ <b>Помилка!</b> Тільки літери/цифри, 3-8 символів."

    if error_msg:
        await update_or_send_msg(bot, message.chat.id, state, error_msg, kb_back())
        return

    await delete_prev_msg(state, bot, message.chat.id)

    # Якщо ми в режимі редагування авто, нам треба взяти старе ім'я з бази, 
    # але функція save_user досить розумна: якщо ми передамо Name=None, вона його не затре.
    # Але для надійності, якщо ми редагуємо тільки авто, ми передаємо тільки авто.
    
    uname = f"@{message.from_user.username}" if message.from_user.username else None
    
    # Тут ми просто оновлюємо все, що назбирали.
    # Якщо це edit_mode="car", то поля name/phone у `data` можуть бути пусті, 
    # тому ми передаємо те, що є, а database.py ігнорує None.
    
    save_user(
        message.from_user.id, 
        data.get('name'), # Буде None, якщо редагуємо тільки авто -> база не змінить ім'я
        uname, 
        data.get('phone'), # Буде None -> база не змінить телефон
        data['model'], 
        data['body'], 
        data['color'], 
        clean_num
    )
    
    await state.clear()
    await state.update_data(role="driver")
    
    msg = await message.answer(f"✅ <b>Дані авто оновлено!</b>\nНомер: <code>{clean_num}</code>", reply_markup=kb_menu("driver"), parse_mode="HTML")
    await state.update_data(last_msg_id=msg.message_id)
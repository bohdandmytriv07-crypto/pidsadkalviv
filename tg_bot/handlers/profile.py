import re
from contextlib import suppress
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
# 🔥 FIX: Додано ReplyKeyboardRemove в імпорти
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from database import get_user, save_user, get_user_rating, format_rating
from states import ProfileStates
from keyboards import kb_back, kb_menu, kb_car_type
from utils import clean_user_input, send_new_clean_msg, delete_prev_msg, update_or_send_msg

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
    
    await state.update_data(name=message.text)
    await state.set_state(ProfileStates.phone)
    
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Надіслати номер", request_contact=True)]], 
        resize_keyboard=True, 
        one_time_keyboard=True
    )
    # Відправляємо нове повідомлення з кнопкою, щоб воно було свіжим
    await message.answer("📱 <b>Ваш номер телефону:</b>\nНатисніть кнопку знизу:", reply_markup=kb, parse_mode="HTML")

@router.message(ProfileStates.phone)
async def process_phone(message: types.Message, state: FSMContext):
    # 🔥 1. Видаляємо клавіатуру "Надіслати номер"
    rm_msg = await message.answer("⏳ Зберігаю...", reply_markup=ReplyKeyboardRemove())
    
    # Видаляємо контакт юзера (щоб чисто було)
    with suppress(Exception): await message.delete()
    
    phone = message.contact.phone_number if message.contact else message.text
    phone = re.sub(r'\D', '', phone)
    if not phone.startswith("380"): phone = f"380{phone[-9:]}"
    phone = f"+{phone}"

    await state.update_data(phone=phone)
    data = await state.get_data()
    
    # Видаляємо повідомлення "Зберігаю..."
    with suppress(Exception): await rm_msg.delete()

    if data.get("role") == "passenger":
        # Передаємо username, якщо є
        uname = f"@{message.from_user.username}" if message.from_user.username else None
        save_user(message.from_user.id, data['name'], uname, phone)
        
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
    await state.update_data(color=message.text)
    await state.set_state(ProfileStates.number)
    await update_or_send_msg(message.bot, message.chat.id, state, "🔢 <b>Держ. номер авто:</b>\nНаприклад: BC1234AA", kb_back())

@router.message(ProfileStates.number)
async def process_number(message: types.Message, state: FSMContext):
    await clean_user_input(message)
    data = await state.get_data()
    
    uname = f"@{message.from_user.username}" if message.from_user.username else None
    
    save_user(
        message.from_user.id, data['name'], uname, 
        data['phone'], data['model'], data['body'], 
        data['color'], message.text.upper()
    )
    
    await state.clear()
    await state.update_data(role="driver")
    
    kb = kb_menu("driver")
    msg = await message.answer("✅ <b>Водій готовий!</b>", reply_markup=kb, parse_mode="HTML")
    await state.update_data(last_msg_id=msg.message_id)
import re
import asyncio
from contextlib import suppress
from aiogram import Router, F, types, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from database import get_user, save_user, get_user_rating, format_rating
from states import ProfileStates
from keyboards import kb_back, kb_menu, kb_car_type, kb_plate_type
from utils import clean_user_input, send_new_clean_msg, update_or_send_msg, delete_prev_msg
from database import get_referral_count
router = Router()

@router.callback_query(F.data == "profile_edit")
async def show_profile(call: types.CallbackQuery, state: FSMContext):
    user = get_user(call.from_user.id)
    data = await state.get_data()
    role = data.get("role")
    
    if not role:
        role = "driver" if user and user['model'] != "-" else "passenger"
        await state.update_data(role=role)
    
    # Красиве відображення замість "None"
    u_name = user['name'] if user['name'] else "Без імені"
    u_phone = user['phone'] if user['phone'] != "-" else "Не вказано"
    
    # Реферальна система
    ref_count = get_referral_count(call.from_user.id)
    bot_info = await call.bot.get_me()
    # Посилання, яким ділитиметься користувач
    share_url = f"https://t.me/share/url?url=https://t.me/{bot_info.username}?start=ref_{call.from_user.id}&text=Привіт! Я їжджу з Підсадка Львів. Приєднуйся!"

    if user and user['phone'] != "-":
        avg, count = get_user_rating(call.from_user.id)
        
        if role == "passenger":
            # 🔥 ВИПРАВЛЕНО: Додано відображення даних, замість "..."
            txt = (
                f"👤 <b>Ваш профіль:</b>\n\n"
                f"📛 {u_name}\n"
                f"📱 {u_phone}\n"
                f"{format_rating(avg, count)}\n\n"
                f"👥 <b>Запрошено друзів:</b> {ref_count}"
            )
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✏️ Змінити дані", callback_data="edit_personal")],
                [InlineKeyboardButton(text="🤝 Запросити друга", url=share_url)],
                [InlineKeyboardButton(text="🔙 В меню", callback_data="menu_home")]
            ])
        else:
            txt = (
                f"🚖 <b>Профіль водія:</b>\n\n"
                f"📛 {u_name}\n"
                f"📱 {u_phone}\n"
                f"🚘 {user['model']} {user['color']}\n"
                f"🔢 {user['number']}\n"
                f"{format_rating(avg, count)}\n\n"
                f"👥 <b>Запрошено друзів:</b> {ref_count}"
            )
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✏️ Змінити ім'я/телефон", callback_data="edit_personal")],
                [InlineKeyboardButton(text="🚘 Змінити авто", callback_data="edit_car")],
                [InlineKeyboardButton(text="🤝 Запросити друга", url=share_url)],
                [InlineKeyboardButton(text="🔙 В меню", callback_data="menu_home")]
            ])
            
        await update_or_send_msg(call.bot, call.message.chat.id, state, txt, kb)
    else:
        await start_full_reg(call, state)

# ==========================================
# 🏁 ТОЧКИ ВХОДУ (Старт редагування)
# ==========================================

@router.callback_query(F.data == "profile_new")
async def start_full_reg(call: types.CallbackQuery, state: FSMContext):
    """Повна реєстрація з нуля"""
    await state.update_data(edit_mode="full")
    await state.set_state(ProfileStates.name)
    await update_or_send_msg(call.bot, call.message.chat.id, state, "📝 <b>Як до вас звертатися?</b>\n(Наприклад: <i>Андрій</i>)", kb_back())

@router.callback_query(F.data == "edit_personal")
async def start_edit_personal(call: types.CallbackQuery, state: FSMContext):
    """Тільки особисті дані"""
    # 🔥 ВИПРАВЛЕННЯ 2: Завантажуємо старі дані, щоб не загубити їх
    user = get_user(call.from_user.id)
    if user:
        await state.update_data(name=user['name'], phone=user['phone'])
        
    await state.update_data(edit_mode="personal")
    await state.set_state(ProfileStates.name)
    await update_or_send_msg(call.bot, call.message.chat.id, state, "📝 <b>Введіть нове ім'я:</b>", kb_back())

@router.callback_query(F.data == "edit_car")
async def start_edit_car(call: types.CallbackQuery, state: FSMContext):
    user = get_user(call.from_user.id)
    if user:
        # 🔥 ВИПРАВЛЕНО ТУТ: Прибрали body=user['body'], бо такої колонки немає
        await state.update_data(
            name=user['name'], 
            phone=user['phone'],
            model=user['model'],
            number=user['number'],
            color=user['color']
        )
    await state.update_data(edit_mode="car")
    await state.set_state(ProfileStates.model)
    await update_or_send_msg(call.bot, call.message.chat.id, state, "🚘 <b>Введіть нову марку та модель:</b>", kb_back())
# ==========================================
# 👤 ОСОБИСТІ ДАНІ
# ==========================================

@router.message(ProfileStates.name)
async def process_name(message: types.Message, state: FSMContext):
    await clean_user_input(message)
    name = message.text.strip()

    if len(name) < 2 or len(name) > 50:
        await update_or_send_msg(
            message.bot, 
            message.chat.id, 
            state, 
            "⚠️ <b>Ім'я занадто довге або коротке!</b>\nСпробуйте ще раз:", 
            kb_back()
        )
        return

    if "<" in name or ">" in name or "/" in name:
        await update_or_send_msg(
            message.bot, 
            message.chat.id, 
            state, 
            "⚠️ <b>Недопустимі символи.</b>\nВведіть просто ім'я:", 
            kb_back()
        )
        return

    await state.update_data(name=name)
    await state.set_state(ProfileStates.phone)
    await delete_prev_msg(state, message.bot, message.chat.id)
    
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Надіслати номер", request_contact=True)]], 
        resize_keyboard=True, 
        one_time_keyboard=True
    )
    msg = await message.answer("📱 <b>Ваш номер телефону:</b>", reply_markup=kb, parse_mode="HTML")
    
    # Обов'язково зберігаємо ID нового повідомлення!
    await state.update_data(last_msg_id=msg.message_id)

@router.message(ProfileStates.phone)
async def process_phone(message: types.Message, state: FSMContext):
    # Перевірка, чи це контакт іншої людини
    if message.contact and message.contact.user_id != message.from_user.id:
        await message.answer("⛔ <b>Це не ваш контакт!</b>")
        return
    
    # Тимчасове повідомлення "Зберігаю..." для видалення клавіатури
    rm_msg = await message.answer("⏳ Зберігаю...", reply_markup=ReplyKeyboardRemove())
    with suppress(Exception): await message.delete() # Видаляємо повідомлення юзера
    
    # Очистка номеру
    raw_phone = message.contact.phone_number if message.contact else message.text
    clean_phone = re.sub(r'[^\d+]', '', raw_phone)

    # Авто-корекція формату (якщо юзер забув + або код країни)
    if len(clean_phone) == 10 and clean_phone.startswith('0'):
        clean_phone = '+38' + clean_phone
    elif len(clean_phone) == 11 and clean_phone.startswith('80'):
        clean_phone = '+3' + clean_phone[1:]
    elif not clean_phone.startswith('+'):
        clean_phone = '+' + clean_phone

    # Перевірка валідності (10-15 цифр)
    if not re.match(r'^\+\d{10,15}$', clean_phone):
        with suppress(Exception): await rm_msg.delete() # Видаляємо "Зберігаю..."
        
        # 🔥 ВИПРАВЛЕННЯ ТУТ:
        # Спочатку видаляємо попереднє повідомлення бота (старе питання або стару помилку)
        await delete_prev_msg(state, message.bot, message.chat.id)
        
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Надіслати номер", request_contact=True)]], resize_keyboard=True, one_time_keyboard=True)
        msg = await message.answer("❌ <b>Невірний формат!</b>\nНомер має починатися з + (напр. +380...)", reply_markup=kb, parse_mode="HTML")
        
        # Запам'ятовуємо ID нової помилки, щоб видалити її наступного разу
        await state.update_data(last_msg_id=msg.message_id)
        return

    final_phone = clean_phone
    await state.update_data(phone=final_phone)
    
    # Видаляємо "Зберігаю..."
    with suppress(Exception): await rm_msg.delete()
    
    # Видаляємо останнє повідомлення (це може бути питання про номер або повідомлення про помилку)
    await delete_prev_msg(state, message.bot, message.chat.id)

    # Логіка збереження та переходу далі
    data = await state.get_data()
    edit_mode = data.get("edit_mode")
    role = data.get("role", "passenger")

    if edit_mode == "personal" or role == "passenger":
        uname = f"@{message.from_user.username}" if message.from_user.username else None
        final_name = data.get('name') 
        
        save_user(message.from_user.id, final_name, uname, final_phone)
        
        pending_trip_id = data.get("pending_booking_id")
        if pending_trip_id:
            await state.clear()
            # Повідомлення про успіх (пропадає, коли з'являється прев'ю поїздки)
            temp_suc = await message.answer("✅ <b>Профіль готовий!</b>", reply_markup=ReplyKeyboardRemove(), parse_mode="HTML")
            await asyncio.sleep(1)
            with suppress(Exception): await temp_suc.delete()
            
            from handlers.passenger import show_trip_preview
            await show_trip_preview(message, state, pending_trip_id)
        else:
            await state.clear()
            await state.update_data(role=role)
            kb = kb_menu(role)
            msg = await message.answer("✅ <b>Особисті дані оновлено!</b>", reply_markup=kb, parse_mode="HTML")
            await state.update_data(last_msg_id=msg.message_id)
    else:
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
    # Транслітерація кирилиці в латиницю для номерів
    translation = str.maketrans("АВЕКМНОРСТІХ", "ABEKMHOPCTIX") 
    clean_num = raw_num.translate(translation)

    error_msg = None
    if data.get("plate_type") == "std":
        if not re.match(r'^[A-Z]{2}\d{4}[A-Z]{2}$', clean_num):
            error_msg = "❌ <b>Невірний формат!</b> Приклад: BC1234AI"
    else:
        if len(clean_num) < 3 or len(clean_num) > 8 or not re.match(r'^[A-Z0-9]+$', clean_num):
            error_msg = "❌ <b>Помилка!</b> Тільки літери/цифри, 3-8 символів."

    if error_msg:
        await update_or_send_msg(bot, message.chat.id, state, error_msg, kb_back())
        return

    await delete_prev_msg(state, bot, message.chat.id)
    uname = f"@{message.from_user.username}" if message.from_user.username else None
    
    # 🔥 ХАК: Об'єднуємо модель і тип кузова, щоб не міняти структуру БД
    full_model = f"{data['model']} ({data['body']})"

    # 🔥 ВИПРАВЛЕНО: Передаємо аргументи чітко по іменах (keyword arguments)
    # Це врятує від плутанини, куди що записується
    save_user(
        user_id=message.from_user.id, 
        name=data.get('name'), 
        username=uname, 
        phone=data.get('phone'), 
        model=full_model,     
        number=clean_num,      
        color=data['color']
    )
    
    await state.clear()
    await state.update_data(role="driver")
    
    msg = await message.answer(f"✅ <b>Дані авто оновлено!</b>\nНомер: <code>{clean_num}</code>", reply_markup=kb_menu("driver"), parse_mode="HTML")
    await state.update_data(last_msg_id=msg.message_id)
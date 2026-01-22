import uuid
from contextlib import suppress
from aiogram import Router, F, types, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

from utils import (
    clean_user_input, is_valid_city, 
    get_city_suggestion, validate_city_real, update_or_send_msg, delete_prev_msg
)
from states import SearchStates
from database import (
    search_trips, add_booking, get_user, get_user_bookings, 
    get_trip_details, delete_booking, get_recent_searches, save_search_history,
    get_user_history, add_subscription, add_or_update_city,
    get_user_rating, format_rating # 👈 Додано для рейтингу
)
from keyboards import kb_back, kb_dates, kb_menu

router = Router()

PAGE_SIZE = 3

# ==========================================
# 🏠 МЕНЮ ПАСАЖИРА
# ==========================================

@router.callback_query(F.data == "role_passenger")
async def passenger_menu_handler(call: types.CallbackQuery, state: FSMContext):
    menu_msg_id = call.message.message_id
    
    await state.clear()
    await state.update_data(role="passenger", last_msg_id=menu_msg_id)
    
    msg = await call.message.edit_text(
        "👋 <b>Меню пасажира</b>\nОберіть дію:",
        reply_markup=kb_menu("passenger"),
        parse_mode="HTML"
    )
    await state.update_data(last_interface_id=msg.message_id, last_msg_id=msg.message_id)


# ==========================================
# 🔍 ПОШУК ПОЇЗДОК
# ==========================================

@router.callback_query(F.data == "pass_find")
async def search_start_handler(call: types.CallbackQuery, state: FSMContext):
    prev_msg_id = call.message.message_id
    
    await state.clear()
    await state.update_data(last_msg_id=prev_msg_id)
    
    # Перевірка профілю
    if not await _check_profile_filled(call):
        return

    await state.set_state(SearchStates.origin)
    
    history = get_recent_searches(call.from_user.id)
    keyboard_rows = []

    # Додаємо історію, якщо є
    if history:
        msg_text = (
            "📜 <b>Ваші часті маршрути:</b>\n\n"
            "👇 Оберіть зі списку або <b>напишіть місто відправлення</b>:"
        )
        for orig, dest in history:
            cb_data = f"hist_{orig}_{dest}"
            keyboard_rows.append([InlineKeyboardButton(text=f"🔄 {orig} ➝ {dest}", callback_data=cb_data)])
    else:
        msg_text = "🔍 <b>Звідки виїжджаємо?</b>\nВведіть місто (напр. Київ):"

    keyboard_rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="role_passenger")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

    await update_or_send_msg(call.bot, call.message.chat.id, state, msg_text, keyboard)


async def _check_profile_filled(call: types.CallbackQuery) -> bool:
    user = get_user(call.from_user.id)
    if not user or not user['phone'] or user['phone'] == "-":
        await call.answer("❌ Спочатку заповніть профіль!", show_alert=True)
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👤 Заповнити профіль", callback_data="profile_edit")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="role_passenger")]
        ])
        
        # Спробуємо відредагувати, якщо не вийде - нове повідомлення
        try:
            await call.message.edit_text(
                "⚠️ <b>Доступ обмежено.</b>\n\nЩоб водій міг з вами зв'язатися, нам потрібен ваш номер телефону.",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        except:
            await call.message.answer("⚠️ Доступ обмежено. Заповніть профіль.", reply_markup=keyboard)
            
        return False
    return True


# --- ОБРОБНИК ІСТОРІЇ (Швидкий пошук) ---

@router.callback_query(F.data.startswith("hist_"))
async def history_search_select(call: types.CallbackQuery, state: FSMContext):
    parts = call.data.split("_")
    origin, dest = parts[1], parts[2]
    
    await state.update_data(origin=origin, dest=dest)
    await state.set_state(SearchStates.date)
    
    await update_or_send_msg(
        call.bot, call.message.chat.id, state,
        f"🚀 Маршрут: <b>{origin} ➝ {dest}</b>\n📅 <b>Коли їдемо?</b>", 
        kb_dates("sdate")
    )


# --- ВВЕДЕННЯ МІСТ ---

@router.message(SearchStates.origin)
async def process_search_origin(message: types.Message, state: FSMContext, bot: Bot):
    await clean_user_input(message)
    raw_text = message.text.strip()

    # 1. Пошук в базі (швидкий)
    suggestion = get_city_suggestion(raw_text)

    if suggestion and suggestion.lower() == raw_text.lower():
        clean_city = suggestion
        add_or_update_city(clean_city)
        
        await state.update_data(origin=clean_city)
        await state.set_state(SearchStates.dest)
        
        await update_or_send_msg(
            bot, message.chat.id, state,
            f"✅ Звідки: <b>{clean_city}</b>\n\n🏁 <b>Куди їдемо?</b>\nВведіть місто:", 
            kb_back()
        )
        return

    # 2. Якщо схоже, але не точне - питаємо
    if suggestion:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"✅ Так, {suggestion}", callback_data=f"fix_orig_{suggestion}")],
            [InlineKeyboardButton(text="❌ Ні, залишити як є", callback_data="fix_orig_ignore")]
        ])
        
        await state.update_data(temp_origin=raw_text)
        
        await update_or_send_msg(
            message.bot, message.chat.id, state,
            f"🤔 Ви написали <b>{raw_text}</b>.\nМожливо, ви мали на увазі <b>{suggestion}</b>?", 
            keyboard
        )
        return

    # 3. Валідація через інтернет (повільна)
    wait_msg = await message.answer("🌍 Перевіряю назву міста...")
    real_name = validate_city_real(raw_text)
    with suppress(TelegramBadRequest): await wait_msg.delete()

    if real_name:
        clean_city = real_name
        add_or_update_city(clean_city)
        
        await state.update_data(origin=clean_city)
        await state.set_state(SearchStates.dest)
        
        await update_or_send_msg(
            message.bot, message.chat.id, state,
            f"✅ Звідки: <b>{clean_city}</b>\n\n🏁 <b>Куди їдемо?</b>\nВведіть місто:", 
            kb_back()
        )
    else:
        await update_or_send_msg(
            message.bot, message.chat.id, state,
            f"❌ <b>Місто '{raw_text}' не знайдено!</b>\nСпробуйте ще раз.", 
            kb_back()
        )


@router.callback_query(F.data.startswith("fix_orig_"))
async def fix_origin_handler(call: types.CallbackQuery, state: FSMContext):
    action = call.data.split("_")[2]
    
    if action == "ignore":
        data = await state.get_data()
        final_city = data.get("temp_origin", "").title()
    else:
        final_city = action

    add_or_update_city(final_city)
    await state.update_data(origin=final_city)
    await state.set_state(SearchStates.dest)
    
    await update_or_send_msg(
        call.bot, call.message.chat.id, state,
        f"✅ Звідки: <b>{final_city}</b>\n\n🏁 <b>Куди їдемо?</b>\nВведіть місто:", 
        kb_back()
    )


@router.message(SearchStates.dest)
async def process_search_dest(message: types.Message, state: FSMContext, bot: Bot):
    await clean_user_input(message)
    raw_text = message.text.strip()

    suggestion = get_city_suggestion(raw_text)

    if suggestion and suggestion.lower() == raw_text.lower():
        clean_city = suggestion
        add_or_update_city(clean_city)
        
        await state.update_data(dest=clean_city)
        await state.set_state(SearchStates.date)
        
        await update_or_send_msg(
            bot, message.chat.id, state,
            f"🏁 Куди: <b>{clean_city}</b>\n\n📅 <b>Коли їдемо?</b>\nОберіть дату:", 
            kb_dates("sdate")
        )
        return

    if suggestion:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"✅ Так, {suggestion}", callback_data=f"fix_dest_{suggestion}")],
            [InlineKeyboardButton(text="❌ Ні, залишити як є", callback_data="fix_dest_ignore")]
        ])
        
        await state.update_data(temp_dest=raw_text)
        
        await update_or_send_msg(
            message.bot, message.chat.id, state,
            f"🤔 Ви написали <b>{raw_text}</b>.\nМожливо, ви мали на увазі <b>{suggestion}</b>?", 
            keyboard
        )
        return

    wait_msg = await message.answer("🌍 Перевіряю назву міста...")
    real_name = validate_city_real(raw_text)
    with suppress(TelegramBadRequest): await wait_msg.delete()

    if real_name:
        clean_city = real_name
        add_or_update_city(clean_city)
        
        await state.update_data(dest=clean_city)
        await state.set_state(SearchStates.date)
        
        await update_or_send_msg(
            message.bot, message.chat.id, state,
            f"🏁 Куди: <b>{clean_city}</b>\n\n📅 <b>Коли їдемо?</b>\nОберіть дату:", 
            kb_dates("sdate")
        )
    else:
        await update_or_send_msg(
            message.bot, message.chat.id, state,
            f"❌ <b>Місто '{raw_text}' не знайдено!</b>\nСпробуйте ще раз.", 
            kb_back()
        )


@router.callback_query(F.data.startswith("fix_dest_"))
async def fix_dest_handler(call: types.CallbackQuery, state: FSMContext):
    action = call.data.split("_")[2]
    
    if action == "ignore":
        data = await state.get_data()
        final_city = data.get("temp_dest", "").title()
    else:
        final_city = action

    add_or_update_city(final_city)
    await state.update_data(dest=final_city)
    await state.set_state(SearchStates.date)
    
    await update_or_send_msg(
        call.bot, call.message.chat.id, state,
        f"🏁 Куди: <b>{final_city}</b>\n\n📅 <b>Коли їдемо?</b>", 
        kb_dates("sdate")
    )


# --- ВИКОНАННЯ ПОШУКУ ---

@router.callback_query(SearchStates.date, F.data.startswith("sdate_"))
async def execute_search(call: types.CallbackQuery, state: FSMContext):
    date_val = call.data.split("_")[1]
    data = await state.get_data()
    
    # Ефект завантаження
    await call.message.edit_text("⏳ <b>Шукаю найкращі варіанти...</b>", parse_mode="HTML")
    
    save_search_history(call.from_user.id, data['origin'], data['dest'])
    raw_trips = search_trips(data['origin'], data['dest'], date_val, call.from_user.id)
    
    # Список для ID повідомлень (щоб потім видалити)
    search_msg_ids = []

    if not raw_trips:
        kb_subscribe = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔔 Сповістити мене", callback_data=f"sub_{data['origin']}_{data['dest']}_{date_val}")],
            [InlineKeyboardButton(text="🔙 Новий пошук", callback_data="pass_find")],
            [InlineKeyboardButton(text="🏠 В меню", callback_data="role_passenger")]
        ])
        
        msg = await call.message.edit_text(
            f"😔 <b>Поїздок не знайдено.</b>\n\n"
            f"Маршрут: <b>{data['origin']} ➝ {data['dest']}</b>\n"
            f"Дата: {date_val}\n\n"
            f"<i>Я можу написати вам, як тільки водій створить таку поїздку!</i>",
            reply_markup=kb_subscribe,
            parse_mode="HTML"
        )
        search_msg_ids.append(msg.message_id)
        await state.update_data(search_msg_ids=search_msg_ids)
        return

    # Якщо знайшли - видаляємо "Шукаю..."
    with suppress(TelegramBadRequest):
        await call.message.delete()

    trips_list = [dict(row) for row in raw_trips]
    await state.update_data(all_trips=trips_list, current_page=0, search_msg_ids=search_msg_ids)
    
    await _render_trips_page(call.message, state)


# ==========================================
# 📄 ПАГІНАЦІЯ (ДИЗАЙН КАРТОК + РЕЙТИНГ)
# ==========================================

async def _render_trips_page(message: types.Message, state: FSMContext):
    data = await state.get_data()
    trips = data.get('all_trips', [])
    page = data.get('current_page', 0)
    search_msg_ids = data.get('search_msg_ids', [])
    
    total_pages = (len(trips) - 1) // PAGE_SIZE + 1
    start_index = page * PAGE_SIZE
    end_index = start_index + PAGE_SIZE
    current_slice = trips[start_index:end_index]
    
    # Заголовок
    if page == 0 and start_index == 0:
        header_msg = await message.answer(f"🔎 <b>Знайдено поїздок: {len(trips)}</b>", parse_mode="HTML")
        search_msg_ids.append(header_msg.message_id)

    # Вивід карток
    for trip in current_slice:
        free_seats = trip['seats_total'] - trip['seats_taken']
        
        # 🔥 Отримуємо рейтинг водія
        avg, count = get_user_rating(trip['user_id'], role="driver")
        rating_str = format_rating(avg, count)
        
        txt = (
            f"🚗 <b>{trip['origin']} ➝ {trip['destination']}</b>\n"
            f"➖➖➖➖➖➖➖➖\n"
            f"📅 <b>{trip['date']}</b> | ⏰ <b>{trip['time']}</b>\n"
            f"💰 Ціна: <b>{trip['price']} грн</b>\n"
            f"💺 Вільно місць: <b>{free_seats}</b>\n"
            f"👤 Водій: {trip['driver_name']} ({rating_str})\n" # Додано рейтинг
            f"🚙 Авто: {trip['model']} {trip['color']}"
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Бронювати місце", callback_data=f"book_{trip['id']}")],
            [InlineKeyboardButton(text="💬 Написати водію", callback_data=f"chat_start_{trip['user_id']}")]
        ])
        
        msg = await message.answer(txt, reply_markup=keyboard, parse_mode="HTML")
        search_msg_ids.append(msg.message_id)
    
    # Кнопки навігації
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data="page_prev"))
    
    if total_pages > 1:
        nav_buttons.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="ignore"))
    
    if end_index < len(trips):
        nav_buttons.append(InlineKeyboardButton(text="Вперед ➡️", callback_data="page_next"))
        
    nav_kb = InlineKeyboardMarkup(inline_keyboard=[
        nav_buttons if nav_buttons else [],
        [InlineKeyboardButton(text="🔍 Новий пошук", callback_data="pass_find")],
        [InlineKeyboardButton(text="🏠 У меню", callback_data="menu_home")]
    ])
    
    # Видалення старої навігації
    old_nav_id = data.get("last_nav_msg_id")
    if old_nav_id:
        with suppress(TelegramBadRequest):
            await message.bot.delete_message(chat_id=message.chat.id, message_id=old_nav_id)

    sent_msg = await message.answer("🔽 Дії:", reply_markup=nav_kb)
    search_msg_ids.append(sent_msg.message_id)
    
    # Оновлюємо стан
    await state.update_data(last_nav_msg_id=sent_msg.message_id, search_msg_ids=search_msg_ids)


@router.callback_query(F.data == "page_next")
async def next_page_handler(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    new_page = data.get('current_page', 0) + 1
    await state.update_data(current_page=new_page)
    await _render_trips_page(call.message, state)


@router.callback_query(F.data == "page_prev")
async def prev_page_handler(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    new_page = max(0, data.get('current_page', 0) - 1)
    await state.update_data(current_page=new_page)
    await _render_trips_page(call.message, state)


@router.callback_query(F.data == "ignore")
async def ignore_click(call: types.CallbackQuery):
    await call.answer()


# ==========================================
# 🎫 БРОНЮВАННЯ (Booking)
# ==========================================

@router.callback_query(F.data.startswith("book_"))
async def process_booking_handler(call: types.CallbackQuery, state: FSMContext):
    trip_id = call.data.split("_")[1]
    passenger_id = call.from_user.id
    
    if not await _check_profile_filled(call):
        return

    success, msg = add_booking(trip_id, passenger_id)
    
    if success:
        trip = get_trip_details(trip_id)
        user = get_user(passenger_id)
        
        # 🔥 Отримуємо рейтинг водія для відображення в успішному бронюванні
        avg, count = get_user_rating(trip['user_id'], role="driver")
        rating_str = format_rating(avg, count)
        
        # --- 1. ОЧИЩЕННЯ ЕКРАНУ ---
        with suppress(TelegramBadRequest):
            await call.message.delete()

        data = await state.get_data()
        ids_to_clean = data.get("search_msg_ids", [])
        if data.get("last_nav_msg_id"): ids_to_clean.append(data.get("last_nav_msg_id"))
        
        for mid in ids_to_clean:
            with suppress(TelegramBadRequest):
                await call.bot.delete_message(chat_id=call.message.chat.id, message_id=mid)
        
        # --- 2. УСПІШНЕ ПОВІДОМЛЕННЯ ---
        all_bookings = get_user_bookings(passenger_id)
        current_booking = next((b for b in all_bookings if str(b['trip_id']) == str(trip_id)), None)
        booking_id = current_booking['id'] if current_booking else None
        
        buttons = []
        if booking_id:
            buttons.append([InlineKeyboardButton(text="❌ Скасувати бронювання", callback_data=f"cancel_book_{booking_id}")])
        buttons.append([InlineKeyboardButton(text="💬 Написати водію", callback_data=f"chat_start_{trip['user_id']}")])
        buttons.append([InlineKeyboardButton(text="🔙 Назад в меню", callback_data="menu_home")])
        
        kb_success = InlineKeyboardMarkup(inline_keyboard=buttons)

        success_msg = await call.message.answer(
            f"✅ <b>Бронювання успішне!</b>\n"
            f"➖➖➖➖➖➖➖➖\n"
            f"🚗 <b>{trip['origin']} ➝ {trip['destination']}</b>\n"
            f"📅 {trip['date']} | ⏰ {trip['time']}\n"
            f"💰 {trip['price']} грн\n\n"
            f"👤 Водій: <b>{trip['name']}</b> ({rating_str})\n"
            f"📞 Тел: <code>{trip['phone']}</code>\n"
            f"🚙 Авто: {trip['model']} {trip['number']}\n"
            f"➖➖➖➖➖➖➖➖\n"
            f"<i>Водію надіслано ваш контакт. Зв'яжіться з ним.</i>",
            reply_markup=kb_success,
            parse_mode="HTML"
        )
        await state.update_data(last_msg_id=success_msg.message_id)

        # Сповіщення водію
        try:
            free_seats = trip['seats_total'] - trip['seats_taken'] - 1
            
            # Рейтинг пасажира
            p_avg, p_count = get_user_rating(passenger_id, role="passenger")
            p_rating_str = format_rating(p_avg, p_count)
            
            driver_msg = (
                f"🆕 <b>Нове бронювання!</b>\n"
                f"🚗 {trip['origin']} -> {trip['destination']}\n"
                f"👤 Пасажир: <b>{user['name']}</b> ({p_rating_str})\n"
                f"📞 Тел: <code>{user['phone']}</code>\n"
                f"💺 Залишилось місць: <b>{free_seats}</b>" 
            )
            kb_driver = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"💬 Написати {user['name']}", callback_data=f"chat_start_{passenger_id}")]
            ])
            await call.bot.send_message(chat_id=trip['user_id'], text=driver_msg, reply_markup=kb_driver, parse_mode="HTML")
        except Exception: pass

    else:
        await call.answer(f"❌ {msg}", show_alert=True)


# ==========================================
# 🗂 МОЇ БРОНЮВАННЯ
# ==========================================

@router.callback_query(F.data == "pass_my_books")
async def show_my_bookings_handler(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    old_msgs = data.get("booking_msg_ids", [])
    if old_msgs:
        for mid in old_msgs:
            with suppress(TelegramBadRequest):
                await call.bot.delete_message(chat_id=call.message.chat.id, message_id=mid)

    with suppress(TelegramBadRequest):
        await call.message.delete()

    bookings = get_user_bookings(call.from_user.id)
    new_msg_ids = []

    if not bookings:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Знайти поїздку", callback_data="pass_find")],
            [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="menu_home")]
        ])
        msg = await call.message.answer(
            "🎫 <b>У вас немає активних бронювань.</b>\n\nБажаєте знайти поїздку?",
            reply_markup=keyboard, parse_mode="HTML"
        )
        new_msg_ids.append(msg.message_id)
        await state.update_data(booking_msg_ids=new_msg_ids)
        return

    header = await call.message.answer("🎫 <b>Ваші активні бронювання:</b>", parse_mode="HTML")
    new_msg_ids.append(header.message_id)
    
    for b in bookings:
        # Рейтинг водія
        avg, count = get_user_rating(b['driver_id'], role="driver")
        rating_str = format_rating(avg, count)
        
        txt = (
            f"🎫 <b>Поїздка до {b['destination']}</b>\n"
            f"🗓 {b['date']} о {b['time']}\n"
            f"📍 {b['origin']} ➝ {b['destination']}\n"
            f"👤 Водій: {b['driver_name']} ({rating_str})\n"
            f"📞 <code>{b['driver_phone']}</code>\n"
            f"💰 {b['price']} грн"
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💬 Написати водію", callback_data=f"chat_start_{b['driver_id']}")],        
            [InlineKeyboardButton(text="❌ Скасувати бронювання", callback_data=f"cancel_book_{b['id']}")],
            [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="menu_home")] 
        ])
        
        msg = await call.message.answer(txt, reply_markup=keyboard, parse_mode="HTML")
        new_msg_ids.append(msg.message_id)

    await state.update_data(booking_msg_ids=new_msg_ids)


@router.callback_query(F.data.startswith("cancel_book_"))
async def cancel_booking_handler(call: types.CallbackQuery, state: FSMContext):
    booking_id = int(call.data.split("_")[2])
    
    info = delete_booking(booking_id, call.from_user.id)
    
    if info:
        await call.answer("✅ Бронювання скасовано!", show_alert=True)
        
        driver_msg = (
            f"❌ <b>Скасування бронювання!</b>\n"
            f"Пасажир <b>{info['passenger_name']}</b> скасував поїздку.\n\n"
            f"🚗 Маршрут: {info['origin']} ➝ {info['destination']}\n"
            f"📅 {info['date']} | ⏰ {info['time']}\n"
            f"✅ Місце автоматично звільнено для інших."
        )
        with suppress(Exception):
            await call.bot.send_message(chat_id=info['driver_id'], text=driver_msg, parse_mode="HTML")
        
        await show_my_bookings_handler(call, state)

    else:
        await call.answer("❌ Помилка скасування.", show_alert=True)
        await show_my_bookings_handler(call, state)


# ==========================================
# 📜 ІСТОРІЯ ТА ПІДПИСКИ
# ==========================================

@router.callback_query(F.data == "pass_history")
async def show_history_handler(call: types.CallbackQuery, state: FSMContext):
    history = get_user_history(call.from_user.id)
    
    kb_back_only = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="menu_home")]
    ])
    
    with suppress(TelegramBadRequest): 
        await call.message.delete()

    if not history:
        await call.message.answer(
            "📜 <b>Ваша історія порожня.</b>\nВи ще не здійснили жодної поїздки.", 
            reply_markup=kb_back_only, parse_mode="HTML"
        )
        return

    await call.message.answer("📜 <b>Ваші минулі поїздки (останні 5):</b>", parse_mode="HTML")
    
    for trip in history[:5]:
        # В історії не завжди є ID водія в старому коді, але краще додати
        # Для простоти тут показуємо без рейтингу або можна додати запит, якщо є ID
        txt = (
            f"✅ <b>Завершено</b>\n"
            f"🚗 {trip['origin']} ➝ {trip['destination']}\n"
            f"📅 {trip['date']} | ⏰ {trip['time']}\n"
            f"👤 Водій: {trip['driver_name']}\n"
            f"💰 {trip['price']} грн"
        )
        await call.message.answer(txt, parse_mode="HTML")
        
    await call.message.answer("↩️ Повернутися:", reply_markup=kb_back_only)


@router.callback_query(F.data.startswith("sub_"))
async def subscribe_handler(call: types.CallbackQuery):
    parts = call.data.split("_")
    
    if len(parts) < 4:
        await call.answer("Помилка даних", show_alert=True)
        return

    origin = parts[1]
    dest = parts[2]
    date_val = parts[3]
    
    add_subscription(call.from_user.id, origin, dest, date_val)
    
    with suppress(TelegramBadRequest):
        await call.message.delete()
    
    await call.message.answer(
        f"🔔 <b>Ви підписалися!</b>\n"
        f"Маршрут: {origin} ➝ {dest} ({date_val})\n"
        f"Я надішлю вам повідомлення, щойно хтось створить таку поїздку.",
        reply_markup=kb_menu("passenger"),
        parse_mode="HTML"
    ) 
    await call.answer()
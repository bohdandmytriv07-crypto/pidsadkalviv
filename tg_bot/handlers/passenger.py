import asyncio
import html
from contextlib import suppress
from aiogram import Router, F, types, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from aiogram.exceptions import TelegramBadRequest

from utils import safe_html, clean_user_input, update_or_send_msg, delete_messages_list, delete_prev_msg
from database import (
    search_trips, search_trips_page, add_booking, get_user, get_user_bookings, 
    get_trip_details, delete_booking, get_recent_searches, save_search_history,
    add_subscription, get_user_rating, format_rating, log_event,
    add_or_update_city, get_passenger_history, 
    get_user_active_bookings_count, can_user_book, log_cancellation_event,
    get_city_suggestion
)
from states import SearchStates
from keyboards import kb_dates, kb_menu, kb_back

# Імпорт валідації міст
from utils import validate_city_real

router = Router()

# Універсальна кнопка для закриття сповіщень
kb_ok = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Зрозуміло", callback_data="hide_msg")]])
PAGE_SIZE = 3

# ==========================================
# 🔥 ПРЕВ'Ю ПОЇЗДКИ (Deep Link)
# ==========================================
async def show_trip_preview(message: types.Message, state: FSMContext, trip_id: str):
    await delete_prev_msg(state, message.bot, message.chat.id)
    
    trip = get_trip_details(trip_id)
    
    if not trip or trip['status'] != 'active':
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 В меню", callback_data="menu_home")]])
        msg = await message.answer("⚠️ <b>Ця поїздка вже неактивна або не існує.</b>", reply_markup=kb, parse_mode="HTML")
        await state.update_data(last_msg_id=msg.message_id)
        return

    if trip['user_id'] == message.from_user.id:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗂 Перейти до моїх поїздок", callback_data="drv_my_trips")],
            [InlineKeyboardButton(text="🏠 В меню", callback_data="menu_home")]
        ])
        msg = await message.answer("😏 <b>Це ваша власна поїздка!</b>\nВи не можете забронювати місце у себе.", reply_markup=kb, parse_mode="HTML")
        await state.update_data(last_msg_id=msg.message_id)
        return

    await state.update_data(role="passenger")

    free_seats = trip['seats_total'] - trip['seats_taken']
    avg, count = get_user_rating(trip['user_id'], role="driver")
    rating_str = format_rating(avg, count)
    
    desc_line = f"\n💬 <i>{trip['description']}</i>" if trip.get('description') else ""
    
    text = (
        f"🚀 <b>Знайдено поїздку!</b>\n\n"
        f"🚗 <b>{trip['origin']} ➝ {trip['destination']}</b>\n"
        f"📅 {trip['date']} | ⏰ {trip['time']}\n"
        f"💰 <b>{trip['price']} грн</b> | 💺 Вільно: <b>{free_seats}</b>\n\n"
        f"👤 Водій: {trip['name']} ({rating_str}){desc_line}\n"
        f"🚙 Авто: {trip['model']} {trip['color']}"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Бронювати місце", callback_data=f"book_{trip['id']}")],
        [InlineKeyboardButton(text="🏠 В головне меню", callback_data="menu_home")]
    ])
    
    msg = await message.answer(text, reply_markup=kb, parse_mode="HTML")
    await state.update_data(trip_msg_ids=[msg.message_id], last_msg_id=msg.message_id)


# ==========================================
# 🏠 МЕНЮ
# ==========================================

@router.callback_query(F.data == "role_passenger")
async def passenger_menu_handler(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await state.update_data(role="passenger")
    await update_or_send_msg(call.bot, call.message.chat.id, state, "👋 <b>Меню пасажира</b>", kb_menu("passenger"))

# ==========================================
# 🔍 ПОШУК (ЗАХИЩЕНО ВІД NoneType)
# ==========================================

@router.callback_query(F.data == "pass_find")
async def search_start_handler(call: types.CallbackQuery, state: FSMContext):
    await delete_messages_list(state, call.bot, call.message.chat.id, "search_msg_ids")
    await delete_messages_list(state, call.bot, call.message.chat.id, "booking_msg_ids")
    await delete_prev_msg(state, call.bot, call.message.chat.id)
    
    await state.set_state(SearchStates.origin)
    history = get_recent_searches(call.from_user.id)
    
    kb_rows = []
    if history:
        for orig, dest in history:
            kb_rows.append([InlineKeyboardButton(text=f"🔄 {orig} ➝ {dest}", callback_data=f"hist_{orig}_{dest}")])
    kb_rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="role_passenger")])
    
    msg_text = "📜 <b>Оберіть зі списку або напишіть місто:</b>" if history else "📍 <b>Звідки виїжджаємо?</b>\nВведіть місто:"
    
    await update_or_send_msg(call.bot, call.message.chat.id, state, msg_text, InlineKeyboardMarkup(inline_keyboard=kb_rows))

@router.callback_query(F.data.startswith("hist_"))
async def history_search_select(call: types.CallbackQuery, state: FSMContext):
    parts = call.data.split("_")
    await state.update_data(origin=parts[1], dest=parts[2])
    await state.set_state(SearchStates.date)
    await update_or_send_msg(call.bot, call.message.chat.id, state, f"🚀 <b>{parts[1]} ➝ {parts[2]}</b>\n📅 <b>Коли їдемо?</b>", kb_dates("sdate"))

@router.message(SearchStates.origin)
async def process_search_origin(message: types.Message, state: FSMContext, bot: Bot):
    await clean_user_input(message)
    
    # 🛡 ЗАХИСТ: Перевірка на текст
    if not message.text:
        await update_or_send_msg(bot, message.chat.id, state, "⚠️ <b>Це не текст!</b>\nНапишіть назву міста:", kb_back())
        return

    text = message.text.strip()
   
    if text.startswith("/") or len(text) > 50 or len(text) < 2:
        await update_or_send_msg(bot, message.chat.id, state, "⚠️ <b>Введіть коректну назву міста (без команд).</b>", kb_back())
        return

    clean_city = await asyncio.to_thread(get_city_suggestion, text)
    
    if not clean_city:
        clean_city = await validate_city_real(text)
    
    if clean_city:
        add_or_update_city(clean_city)
        await state.update_data(origin=clean_city)
        await state.set_state(SearchStates.dest)
        await update_or_send_msg(bot, message.chat.id, state, f"✅ Звідки: <b>{clean_city}</b>\n\n🏁 <b>Куди їдемо?</b>", kb_back())
    else:
        await update_or_send_msg(bot, message.chat.id, state, "❌ <b>Місто не знайдено.</b> Спробуйте ще раз:", kb_back())

@router.message(SearchStates.dest)
async def process_search_dest(message: types.Message, state: FSMContext, bot: Bot):
    await clean_user_input(message)
    
    # 🛡 ЗАХИСТ: Перевірка на текст
    if not message.text:
        await update_or_send_msg(bot, message.chat.id, state, "⚠️ <b>Це не текст!</b>\nНапишіть назву міста:", kb_back())
        return

    text = message.text.strip()
    
    if text.startswith("/") or len(text) > 50 or len(text) < 2:
        await update_or_send_msg(bot, message.chat.id, state, "⚠️ <b>Введіть коректну назву міста.</b>", kb_back())
        return

    clean_city = await asyncio.to_thread(get_city_suggestion, text)
    
    if not clean_city:
        clean_city = await validate_city_real(text)
    
    if clean_city:
        data = await state.get_data()
        origin_city = data.get('origin', '').lower()
        
        if clean_city.lower() == origin_city:
            await update_or_send_msg(bot, message.chat.id, state, f"⚠️ <b>Ви вже у місті {clean_city}!</b>\nОберіть інше місто призначення:", kb_back())
            return

        add_or_update_city(clean_city)
        await state.update_data(dest=clean_city)
        await state.set_state(SearchStates.date)
        await update_or_send_msg(bot, message.chat.id, state, f"🏁 Куди: <b>{clean_city}</b>\n\n📅 <b>Оберіть дату:</b>", kb_dates("sdate"))
    else:
        await update_or_send_msg(bot, message.chat.id, state, "❌ <b>Місто не знайдено.</b> Спробуйте ще раз:", kb_back())

@router.callback_query(SearchStates.date, F.data.startswith("sdate_"))
async def execute_search(call: types.CallbackQuery, state: FSMContext):
    date_val = call.data.split("_")[1]
    data = await state.get_data()
    
    with suppress(TelegramBadRequest): await call.message.delete()
    save_search_history(call.from_user.id, data['origin'], data['dest'])
    
    await state.update_data(date=date_val, current_page=0, search_msg_ids=[])
    
    trips, count = await asyncio.to_thread(
        search_trips_page, 
        data['origin'], data['dest'], date_val, call.from_user.id, PAGE_SIZE, 0
    )
    
    if not trips:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔔 Сповістити мене", callback_data=f"sub_{data['origin']}_{data['dest']}_{date_val}")],
            [InlineKeyboardButton(text="🔍 Новий пошук", callback_data="pass_find")],
            [InlineKeyboardButton(text="🏠 В меню", callback_data="role_passenger")]
        ])
        msg = await call.message.answer(f"😔 <b>Поїздок не знайдено.</b>\n{data['origin']} -> {data['dest']} на {date_val}", reply_markup=kb, parse_mode="HTML")
        await state.update_data(search_msg_ids=[msg.message_id])
        log_event(call.from_user.id, "search_empty", f"{data['origin']}->{data['dest']}")
        return

    log_event(call.from_user.id, "search_success", f"{data['origin']}->{data['dest']} ({count})")
    await _render_trips_page(call.message, state)

# ==========================================
# 📄 ПАГІНАЦІЯ
# ==========================================

async def _render_trips_page(message: types.Message, state: FSMContext):
    await delete_messages_list(state, message.bot, message.chat.id, "search_msg_ids")

    data = await state.get_data()
    page = data.get('current_page', 0)
    
    trips, total_count = await asyncio.to_thread(
        search_trips_page, 
        data['origin'], data['dest'], data['date'], 
        message.chat.id, PAGE_SIZE, page * PAGE_SIZE
    )
    
    if total_count == 0: total_pages = 1
    else: total_pages = (total_count - 1) // PAGE_SIZE + 1
    
    msg_ids = []
    
    h = await message.answer(f"🔎 <b>Знайдено {total_count} варіантів (Стор. {page+1}/{total_pages})</b>", parse_mode="HTML")
    msg_ids.append(h.message_id)
    
    for trip in trips:
        avg, count = get_user_rating(trip['user_id'], role="driver")
        
        safe_desc = safe_html(trip.get('description', ''))
        desc_line = f"\n💬 <i>{safe_desc}</i>" if safe_desc else ""
        
        safe_driver_name = safe_html(trip['driver_name'])
        safe_origin = safe_html(trip['origin'])
        safe_dest = safe_html(trip['destination'])
        safe_car = safe_html(f"{trip['model']} {trip['color']}")

        txt = (
            f"🚗 <b>{safe_origin} ➝ {safe_dest}</b>\n"
            f"📅 {trip['date']} | ⏰ {trip['time']} | 💰 <b>{trip['price']} грн</b>\n"
            f"👤 {safe_driver_name} ({format_rating(avg, count)}){desc_line}\n"
            f"🚙 {safe_car}"
        )     
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Бронювати", callback_data=f"book_{trip['id']}")],
            [InlineKeyboardButton(text="💬 Написати", callback_data=f"chat_start_{trip['user_id']}")]
        ])
        m = await message.answer(txt, reply_markup=kb, parse_mode="HTML")
        msg_ids.append(m.message_id)
        
    nav_btns = []
    if page > 0: 
        nav_btns.append(InlineKeyboardButton(text="⬅️", callback_data="page_prev"))
    if (page + 1) * PAGE_SIZE < total_count: 
        nav_btns.append(InlineKeyboardButton(text="➡️", callback_data="page_next"))
    
    kb_nav = InlineKeyboardMarkup(inline_keyboard=[
        nav_btns,
        [InlineKeyboardButton(text="🔍 Новий пошук", callback_data="pass_find")],
        [InlineKeyboardButton(text="🏠 В меню", callback_data="menu_home")]
    ])
    
    nav_msg = await message.answer("🔽 Навігація:", reply_markup=kb_nav)
    msg_ids.append(nav_msg.message_id)
    
    await state.update_data(search_msg_ids=msg_ids)

@router.callback_query(F.data == "page_next")
async def next_page(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.update_data(current_page=data['current_page'] + 1)
    await _render_trips_page(call.message, state)

@router.callback_query(F.data == "page_prev")
async def prev_page(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.update_data(current_page=data['current_page'] - 1)
    await _render_trips_page(call.message, state)

# ==========================================
# 🎫 БРОНЮВАННЯ
# ==========================================

@router.callback_query(F.data.startswith("book_"))
async def book_trip(call: types.CallbackQuery, state: FSMContext):
    await delete_messages_list(state, call.bot, call.message.chat.id, "search_msg_ids")
    await delete_messages_list(state, call.bot, call.message.chat.id, "trip_msg_ids")
    
    await delete_prev_msg(state, call.bot, call.message.chat.id)

    user_id = call.from_user.id
    
    allowed, reason = can_user_book(user_id)
    if not allowed:
        await call.answer("Блокування дій!", show_alert=True)
        await call.message.answer(reason, parse_mode="HTML")
        return

    active_count = get_user_active_bookings_count(user_id)
    if active_count >= 2:
        await call.answer("⚠️ Ліміт! У вас вже є 2 активні поїздки.", show_alert=True)
        return

    user = get_user(user_id)
    
    with suppress(TelegramBadRequest): await call.message.delete()

    if not user or user['phone'] == "-":
        trip_id = call.data.split("_")[1]
        await state.update_data(pending_booking_id=trip_id)

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👤 Заповнити профіль", callback_data="profile_edit")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_home")]
        ])
        msg = await call.message.answer("⚠️ <b>Потрібен номер телефону!</b>\nЩоб водій міг з вами зв'язатися.", reply_markup=kb, parse_mode="HTML")
        await state.update_data(last_msg_id=msg.message_id)
        return

    trip_id = call.data.split("_")[1]
    success, msg_text = add_booking(trip_id, user_id)
    
    if success:
        log_event(user_id, "booking_success", f"trip_{trip_id}")
        trip = get_trip_details(trip_id)
        
        # 🔥 ФІКС ПРОБЛЕМИ: Очистка ReplyKeyboard
        rm_msg = await call.message.answer("⏳", reply_markup=ReplyKeyboardRemove())
        with suppress(Exception): await rm_msg.delete()

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💬 Написати водію", callback_data=f"chat_start_{trip['user_id']}")],
            [InlineKeyboardButton(text="🏠 В меню", callback_data="menu_home")]
        ])
        
        msg = await call.message.answer(
            f"✅ <b>Успішно!</b>\nВи забронювали місце до {trip['destination']}.\nВодій: {trip['name']} ({trip['phone']})",
            reply_markup=kb, parse_mode="HTML"
        )
        await state.update_data(last_msg_id=msg.message_id)
        
        with suppress(Exception):
            await call.bot.send_message(
                trip['user_id'], 
                f"🆕 <b>Новий пасажир!</b>\nНа ваш рейс додався {call.from_user.full_name}.", 
                parse_mode="HTML", 
                reply_markup=kb_ok
            )
            
    else:
        await call.answer(msg_text, show_alert=True)
        kb = kb_menu("passenger")
        msg = await call.message.answer("❌ <b>Помилка бронювання.</b>", reply_markup=kb, parse_mode="HTML")
        await state.update_data(last_msg_id=msg.message_id)

# ==========================================
# 🎫 МОЇ БРОНЮВАННЯ
# ==========================================

@router.callback_query(F.data == "pass_my_books")
async def show_bookings(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await delete_messages_list(state, call.bot, call.message.chat.id, "booking_msg_ids")
    await delete_messages_list(state, call.bot, call.message.chat.id, "search_msg_ids")
    await delete_prev_msg(state, call.bot, call.message.chat.id)
    
    with suppress(TelegramBadRequest): await call.message.delete()
    
    try:
        bookings = get_user_bookings(call.from_user.id)
    except Exception as e:
        print(f"❌ DB Error: {e}")
        bookings = []

    msg_ids = []
    
    if not bookings:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 В меню", callback_data="menu_home")]])
        m = await call.message.answer("🎫 <b>Активних бронювань немає.</b>", reply_markup=kb, parse_mode="HTML")
        msg_ids.append(m.message_id)
    else:
        h = await call.message.answer("🎫 <b>Активні бронювання:</b>", parse_mode="HTML")
        msg_ids.append(h.message_id)
        
        for b in bookings:
            d_name = b.get('driver_name') or 'Водій'
            d_phone = b.get('driver_phone', '-')
            
            if d_phone != '-':
                d_phone_fmt = f"<a href='tel:{d_phone}'>{d_phone}</a>"
            else:
                d_phone_fmt = "приховано"

            txt = (
                f"📍 <b>{b['destination']}</b>\n"
                f"🚗 Звідки: {b['origin']}\n"
                f"🗓 {b['date']} о {b['time']}\n"
                f"👤 Водій: {d_name} ({d_phone_fmt})"
            )
            
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💬 Чат", callback_data=f"chat_start_{b['driver_id']}")],
                [InlineKeyboardButton(text="❌ Скасувати", callback_data=f"ask_cancel_bk_{b['id']}")]
            ])
            m = await call.message.answer(txt, reply_markup=kb, parse_mode="HTML")
            msg_ids.append(m.message_id)
            
        f = await call.message.answer("🔽 Меню:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 Додому", callback_data="menu_home")]]))
        msg_ids.append(f.message_id)

    await state.update_data(booking_msg_ids=msg_ids)

@router.callback_query(F.data == "pass_history")
async def show_passenger_history_handler(call: types.CallbackQuery, state: FSMContext):
    await call.answer() 
    await delete_messages_list(state, call.bot, call.message.chat.id, "booking_msg_ids")
    await delete_prev_msg(state, call.bot, call.message.chat.id)
    with suppress(TelegramBadRequest): await call.message.delete()
    
    try:
        history = get_passenger_history(call.from_user.id)
    except Exception: history = []

    msg_ids = []
    if not history:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 В меню", callback_data="menu_home")]])
        m = await call.message.answer("📜 <b>Історія порожня.</b>", reply_markup=kb, parse_mode="HTML")
        msg_ids.append(m.message_id)
    else:
        h = await call.message.answer("📜 <b>Ваші минулі поїздки:</b>", parse_mode="HTML")
        msg_ids.append(h.message_id)
        for trip in history:
            txt = (
                f"✅ <b>{trip['origin']} ➝ {trip['destination']}</b>\n"
                f"📅 {trip['date']} | 💰 {trip['price']} грн\n"
                f"👤 Водій: {trip['driver_name']}"
            )
            m = await call.message.answer(txt, parse_mode="HTML")
            msg_ids.append(m.message_id)
        f = await call.message.answer("🔽 Меню:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 Додому", callback_data="menu_home")]]))
        msg_ids.append(f.message_id)
    await state.update_data(booking_msg_ids=msg_ids)

# ==========================================
# 🔥 ПІДТВЕРДЖЕННЯ СКАСУВАННЯ БРОНІ
# ==========================================
@router.callback_query(F.data.startswith("ask_cancel_bk_"))
async def ask_cancel_booking(call: types.CallbackQuery):
    bid = call.data.split("_")[3]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ ТАК, скасувати", callback_data=f"conf_cancel_bk_{bid}")],
        [InlineKeyboardButton(text="🔙 НІ", callback_data="pass_my_books")]
    ])
    await call.message.edit_text("⚠️ <b>Ви впевнені, що хочете скасувати бронювання?</b>", reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data.startswith("conf_cancel_bk_"))
async def confirm_cancel_booking(call: types.CallbackQuery, state: FSMContext):
    info = delete_booking(int(call.data.split("_")[3]), call.from_user.id)
    if info:
        log_cancellation_event(call.from_user.id) 
        await call.answer("Скасовано.")
        with suppress(Exception): 
            p_name = info['passenger_name'] or "Пасажир"
            await call.bot.send_message(info['driver_id'], f"❌ <b>{p_name} скасував бронювання.</b>\nМісце знову вільне.", parse_mode="HTML", reply_markup=kb_ok)
        await show_bookings(call, state)

@router.callback_query(F.data.startswith("sub_"))
async def sub_handler(call: types.CallbackQuery, state: FSMContext):
    p = call.data.split("_")
    add_subscription(call.from_user.id, p[1], p[2], p[3])
    
    with suppress(TelegramBadRequest): await call.message.delete()
    
    await call.answer("Підписано! Я повідомлю, коли з'явиться поїздка.", show_alert=True)
    
    # 🔥 ФІКС ПРОБЛЕМИ: Очистка ReplyKeyboard
    rm_msg = await call.message.answer("⏳", reply_markup=ReplyKeyboardRemove())
    with suppress(Exception): await rm_msg.delete()

    kb = kb_menu("passenger")
    msg = await call.message.answer("✅ <b>Успішно підписано.</b>\nЩо далі?", reply_markup=kb, parse_mode="HTML")
    await state.update_data(last_msg_id=msg.message_id)
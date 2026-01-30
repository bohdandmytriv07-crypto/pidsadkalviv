import uuid
import re
from datetime import datetime
from urllib.parse import quote 
from contextlib import suppress
from aiogram import Router, F, types, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest
import pytz
# Імпорти з бази даних
from database import (
    get_user, save_user, create_trip, get_driver_active_trips, 
    get_trip_passengers, cancel_trip_full, kick_passenger, 
    get_last_driver_trip, get_subscribers_for_trip,
    add_or_update_city, finish_trip, log_event,
    get_driver_history
)
from handlers.rating import ask_for_ratings 
from states import TripStates
from keyboards import kb_back, kb_dates, kb_menu

# Імпорти утиліт
from utils import (
    clean_user_input, update_or_send_msg, 
    get_city_suggestion, validate_city_real,
    delete_messages_list
)

router = Router()

# ==========================================
# 🚗 СТВОРЕННЯ ПОЇЗДКИ
# ==========================================

@router.callback_query(F.data == "drv_create")
async def start_create_trip_handler(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    # 🔥 ЧИСТКА: Якщо у водія був відкритий список поїздок - видаляємо його
    await delete_messages_list(state, bot, call.message.chat.id, "trip_msg_ids")
    
    await state.update_data(last_msg_id=call.message.message_id, role="driver")
    
    user = get_user(call.from_user.id)
    if not user: save_user(call.from_user.id, call.from_user.full_name, "-")

    # Перевірка профілю (Авто + Телефон)
    if not user or user['phone'] == "-" or user['model'] == "-" or user['number'] == "-":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚘 Додати авто та телефон", callback_data="profile_edit")],
            [InlineKeyboardButton(text="🔙 В меню", callback_data="menu_home")]
        ])
        await update_or_send_msg(bot, call.message.chat.id, state, "⚠️ <b>Ви не можете створити поїздку!</b>\nПотрібно вказати авто та номер телефону в профілі.", kb)
        return

    last_trip = get_last_driver_trip(call.from_user.id)
    if last_trip:
        trip_details = (
            f"🔄 <b>Повторити минулу поїздку?</b>\n\n"
            f"🚗 <b>{last_trip['origin']} ➝ {last_trip['destination']}</b>\n"
            f"💰 {last_trip['price']} грн | 💺 {last_trip['seats_total']} місць"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚡️ Так, повторити", callback_data="drv_repeat_last")],
            [InlineKeyboardButton(text="🆕 Ні, новий маршрут", callback_data="drv_new_route")],
            [InlineKeyboardButton(text="🔙 Скасувати", callback_data="menu_home")]
        ])
        await update_or_send_msg(bot, call.message.chat.id, state, trip_details, kb)
    else:
        await _start_new_trip_questions(call.message.chat.id, state, bot)


@router.callback_query(F.data == "drv_new_route")
async def new_route_selected(call: types.CallbackQuery, state: FSMContext):
    await _start_new_trip_questions(call.message.chat.id, state, call.bot)

@router.callback_query(F.data == "drv_repeat_last")
async def repeat_route_selected(call: types.CallbackQuery, state: FSMContext):
    last_trip = get_last_driver_trip(call.from_user.id)
    await state.update_data(
        origin=last_trip['origin'], destination=last_trip['destination'],
        seats=str(last_trip['seats_total']), saved_price=last_trip['price']
    )
    await state.set_state(TripStates.date)
    await update_or_send_msg(call.bot, call.message.chat.id, state, "📅 <b>Дата нової поїздки?</b>", kb_dates("tripdate"))


async def _start_new_trip_questions(chat_id, state: FSMContext, bot: Bot):
    await state.set_state(TripStates.origin)
    await update_or_send_msg(bot, chat_id, state, "📍 <b>Звідки виїжджаємо?</b>\nВведіть місто (напр. Львів):", kb_back())


@router.message(TripStates.origin)
async def process_origin(message: types.Message, state: FSMContext, bot: Bot):
    await clean_user_input(message)
    
    if message.text.startswith("/"):
        await update_or_send_msg(bot, message.chat.id, state, "⚠️ <b>Це схоже на команду.</b>\nБудь ласка, введіть назву міста:", kb_back())
        return

    raw_text = message.text.strip()
    
    clean_city = get_city_suggestion(raw_text)
    if not clean_city:
        clean_city = await validate_city_real(raw_text)
    
    if clean_city:
        add_or_update_city(clean_city)
        await state.update_data(origin=clean_city)
        await state.set_state(TripStates.destination)
        await update_or_send_msg(bot, message.chat.id, state, f"✅ Звідки: <b>{clean_city}</b>\n\n🏁 <b>Куди їдемо?</b>\nВведіть місто:", kb_back())
    else:
        await update_or_send_msg(bot, message.chat.id, state, f"❌ <b>Не знайшов місто '{raw_text}'.</b>\nСпробуйте ще раз:", kb_back())


@router.message(TripStates.destination)
async def process_destination(message: types.Message, state: FSMContext, bot: Bot):
    await clean_user_input(message)
    
    if message.text.startswith("/"):
        await update_or_send_msg(bot, message.chat.id, state, "⚠️ <b>Введіть назву міста, а не команду.</b>", kb_back())
        return

    raw_text = message.text.strip()
    
    clean_city = get_city_suggestion(raw_text)
    if not clean_city:
        clean_city = await validate_city_real(raw_text)

    if clean_city:
        add_or_update_city(clean_city)
        await state.update_data(destination=clean_city)
        await state.set_state(TripStates.date)
        await update_or_send_msg(bot, message.chat.id, state, f"🏁 Куди: <b>{clean_city}</b>\n\n📅 <b>Коли плануєте поїздку?</b>", kb_dates("tripdate"))
    else:
        await update_or_send_msg(bot, message.chat.id, state, f"❌ <b>Не знайшов місто '{raw_text}'.</b>\nСпробуйте ще раз:", kb_back())


@router.callback_query(TripStates.date)
async def process_date(call: types.CallbackQuery, state: FSMContext):
    date_val = call.data.split("_")[1]
    await state.update_data(date=date_val)
    await state.set_state(TripStates.time)
    await update_or_send_msg(call.bot, call.message.chat.id, state, f"📅 Дата: <b>{date_val}</b>\n\n🕒 <b>Введіть час виїзду:</b>\nФормат ГГ:ХХ (напр. 18:30)", kb_back())


# Не забудь додати імпорт нової функції з бази зверху файлу:
from database import save_trip, get_last_driver_trip, get_active_driver_trips  # <--- ДОДАЙ get_active_driver_trips

@router.message(TripStates.time)
async def process_time(message: types.Message, state: FSMContext, bot: Bot):
    await clean_user_input(message)
    if not re.match(r"^([01]\d|2[0-3]):([0-5]\d)$", message.text):
        await update_or_send_msg(bot, message.chat.id, state, "⚠️ <b>Невірний формат!</b>\nВведіть час так: 09:00 або 18:30", kb_back())
        return

    data = await state.get_data()
    date_str = data.get('date') # Наприклад "30.01"
    time_str = message.text     # Наприклад "14:00"
    
    try:
        # 1. Створюємо об'єкт часу для НОВОЇ поїздки
        kyiv_tz = pytz.timezone('Europe/Kyiv')
        now_kyiv = datetime.now(kyiv_tz)
        
        trip_dt_naive = datetime.strptime(f"{date_str}.{now_kyiv.year} {time_str}", "%d.%m.%Y %H:%M")
        trip_dt = kyiv_tz.localize(trip_dt_naive)
        
        # Корекція року (якщо це поїздка на наступний рік)
        if (now_kyiv - trip_dt).days > 30:
             trip_dt = trip_dt.replace(year=now_kyiv.year + 1)
        
        # Перевірка: чи не минув час
        if trip_dt < now_kyiv:
             await update_or_send_msg(bot, message.chat.id, state, "⚠️ <b>Цей час вже минув!</b>\nВведіть коректний час виїзду:", kb_back())
             return

        # 🔥 2. ПЕРЕВІРКА НА ДУБЛІКАТИ (Нова логіка)
        active_trips = get_active_driver_trips(message.from_user.id)
        
        for row in active_trips:
            if row['date'] == date_str:
                
                existing_dt_naive = datetime.strptime(f"{row['date']}.{now_kyiv.year} {row['time']}", "%d.%m.%Y %H:%M")
                existing_dt = kyiv_tz.localize(existing_dt_naive)
                
                
                diff_seconds = abs((trip_dt - existing_dt).total_seconds())
                
                
                if diff_seconds < 7200:
                    await update_or_send_msg(bot, message.chat.id, state, 
                        f"⚠️ <b>Неможливо створити поїздку!</b>\n\n"
                        f"У вас вже є активна поїздка на <b>{row['time']}</b>.\n"
                        f"Мінімальний інтервал між рейсами — 2 години.", 
                        kb_back()
                    )
                    return

    except ValueError:
        pass 

    await state.update_data(time=message.text)
    
    if data.get('saved_price'):
        await finalize_trip_creation(message, state, bot, price_override=data.get('saved_price'))
        return

    await state.set_state(TripStates.seats)
    await update_or_send_msg(bot, message.chat.id, state, "💺 <b>Скільки вільних місць?</b>\nВведіть цифру (1-8):", kb_back())


@router.message(TripStates.seats)
async def process_seats(message: types.Message, state: FSMContext, bot: Bot):
    await clean_user_input(message)
    if not message.text.isdigit() or not (1 <= int(message.text) <= 8):
        await update_or_send_msg(bot, message.chat.id, state, "⚠️ <b>Введіть цифру від 1 до 8:</b>", kb_back())
        return

    await state.update_data(seats=int(message.text))
    await state.set_state(TripStates.price)
    await update_or_send_msg(bot, message.chat.id, state, "💰 <b>Ціна за 1 місце (грн):</b>\nНапишіть тільки суму:", kb_back())


@router.message(TripStates.price)
async def process_price(message: types.Message, state: FSMContext, bot: Bot):
    await clean_user_input(message)
    try:
        price = int(message.text)
        if price <= 0: raise ValueError
        if price > 5000:
            await update_or_send_msg(bot, message.chat.id, state, "⚠️ <b>Занадто висока ціна!</b>\nВкажіть реальну суму до 5000 грн.", kb_back())
            return
            
    except ValueError:
        await update_or_send_msg(bot, message.chat.id, state, "⚠️ <b>Ціна має бути числом > 0!</b>", kb_back())
        return

    await state.update_data(price=price)
    
    await state.set_state(TripStates.description)
    kb_skip = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➡️ Пропустити", callback_data="skip_desc")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_home")]
    ])
    
    await update_or_send_msg(
        bot, message.chat.id, state, 
        "💬 <b>Додайте коментар (необов'язково):</b>\n\n"
        "Напишіть деталі (напр. <i>'Беру передачі', 'Їду через центр'</i>) або натисніть кнопку:", 
        kb_skip
    )


@router.callback_query(F.data == "skip_desc")
async def skip_description(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    await finalize_trip_creation(call.message, state, bot, desc_text="")

@router.message(TripStates.description)
async def process_description(message: types.Message, state: FSMContext, bot: Bot):
    await clean_user_input(message)
    text = message.text.strip()
    
  
    if len(text) > 200:
        await update_or_send_msg(bot, message.chat.id, state, "⚠️ <b>Занадто довгий текст!</b> Скоротіть до 200 символів.", kb_back())
        return
        
    if "<" in text or ">" in text:
        await update_or_send_msg(bot, message.chat.id, state, "⚠️ <b>Приберіть символи < та >.</b>\nВони заборонені.", kb_back())
        return

    await finalize_trip_creation(message, state, bot, desc_text=text)


async def finalize_trip_creation(message: types.Message, state: FSMContext, bot: Bot, price_override=None, desc_text=None):
    data = await state.get_data()
    final_price = int(price_override) if price_override else data.get('price')
    description = desc_text if desc_text is not None else ""
    
    trip_id = str(uuid.uuid4())[:8]
    create_trip(
        trip_id, message.chat.id, 
        data['origin'], data['destination'], 
        data['date'], data['time'], 
        int(data['seats']), final_price, 
        description
    )
    
    log_event(message.chat.id, "trip_created", f"{data['origin']}->{data['destination']}")
    
    # 🔥 FIX: Правильне кодування посилання
    bot_info = await bot.get_me()
    bot_username = bot_info.username
    deep_link = f"https://t.me/{bot_username}?start=book_{trip_id}"
    
    share_text_raw = f"🚗 Їду {data['origin']} -> {data['destination']} ({data['date']} {data['time']}). Бронюй тут:"
    share_text_encoded = quote(share_text_raw)
    share_url = f"https://t.me/share/url?url={deep_link}&text={share_text_encoded}"
    
    desc_view = f"\n💬 <i>{description}</i>" if description else ""
    
    text = (
        f"✅ <b>Поїздку створено!</b>\n\n"
        f"🚗 {data['origin']} ➝ {data['destination']}\n"
        f"📅 {data['date']} | ⏰ {data['time']}\n"
        f"💰 {final_price} грн{desc_view}"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Поділитися", url=share_url)],
        [InlineKeyboardButton(text="🔙 В меню", callback_data="menu_home")]
    ])
    
    await update_or_send_msg(bot, message.chat.id, state, text, kb)
    await _notify_subscribers(bot, message.chat.id, trip_id, data, final_price, description)


async def _notify_subscribers(bot, driver_id, trip_id, trip_data, price, description=""):
    subscribers = get_subscribers_for_trip(trip_data['origin'], trip_data['destination'], trip_data['date'])
    
    desc_line = f"\n💬 <i>{description}</i>" if description else ""
    
    text = (
        f"🔔 <b>Знайдено поїздку!</b>\n"
        f"🚗 {trip_data['origin']} ➝ {trip_data['destination']}\n"
        f"⏰ {trip_data['time']} | 💰 {price} грн{desc_line}"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Бронювати", callback_data=f"book_{trip_id}")]])
    
    for sub_id in subscribers:
        if sub_id != driver_id:
            with suppress(Exception): await bot.send_message(sub_id, text, reply_markup=kb, parse_mode="HTML")


# ==========================================
# 🗂 КЕРУВАННЯ ПОЇЗДКАМИ
# ==========================================

@router.callback_query(F.data == "drv_my_trips")
async def show_driver_trips(call: types.CallbackQuery, state: FSMContext):
    await delete_messages_list(state, call.bot, call.message.chat.id, "trip_msg_ids")
    with suppress(TelegramBadRequest): await call.message.delete()

    trips = get_driver_active_trips(call.from_user.id)
    new_msg_ids = []

    if not trips:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📜 Історія поїздок", callback_data="drv_history")],
            [InlineKeyboardButton(text="🔙 В меню", callback_data="menu_home")]
        ])
        msg = await call.message.answer("🗂 <b>Активних поїздок немає.</b>", reply_markup=kb, parse_mode="HTML")
        new_msg_ids.append(msg.message_id)
        await state.update_data(trip_msg_ids=new_msg_ids)
        return

    header = await call.message.answer("🗂 <b>Активні поїздки:</b>", parse_mode="HTML")
    new_msg_ids.append(header.message_id)
    
    bot_info = await call.bot.get_me()

    for trip in trips:
        free = trip['seats_total'] - trip['seats_taken']
        text = f"🚗 <b>{trip['origin']} ➝ {trip['destination']}</b>\n📅 {trip['date']} | ⏰ {trip['time']}\n💰 {trip['price']} грн | Вільно: {free}"
        
        kb_rows = []
        passengers = get_trip_passengers(trip['id'])
        
        if passengers:
            text += "\n\n👥 <b>Пасажири:</b>"
            for p in passengers:
                text += f"\n👤 {p['name']} ({p['phone']})"
                kb_rows.append([
                    InlineKeyboardButton(text=f"💬 Чат: {p['name']}", callback_data=f"chat_start_{p['user_id']}"),
                    InlineKeyboardButton(text="🚫 Висадити", callback_data=f"kick_{p['booking_id']}")
                ])
        
        # 🔥 FIX: Правильне кодування посилання в списку
        deep_link = f"https://t.me/{bot_info.username}?start=book_{trip['id']}"
        share_text_raw = f"🚗 Їду {trip['origin']} -> {trip['destination']} ({trip['date']} о {trip['time']}). Бронюй місце тут:"
        share_text_encoded = quote(share_text_raw)
        share_url = f"https://t.me/share/url?url={deep_link}&text={share_text_encoded}"

        kb_rows.append([InlineKeyboardButton(text="📢 Поділитися поїздкою", url=share_url)])
        kb_rows.append([InlineKeyboardButton(text="🏁 Завершити", callback_data=f"drv_finish_{trip['id']}")])
        kb_rows.append([InlineKeyboardButton(text="❌ Скасувати", callback_data=f"drv_ask_cancel_{trip['id']}")])
        
        card = await call.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows), parse_mode="HTML")
        new_msg_ids.append(card.message_id)

    kb_back_btn = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 Історія поїздок", callback_data="drv_history")],
        [InlineKeyboardButton(text="🔙 В меню", callback_data="menu_home")]
    ])
    footer = await call.message.answer("🔽 Управління:", reply_markup=kb_back_btn)
    new_msg_ids.append(footer.message_id)
    
    await state.update_data(trip_msg_ids=new_msg_ids)


@router.callback_query(F.data == "drv_history")
async def show_driver_history(call: types.CallbackQuery, state: FSMContext):
    await delete_messages_list(state, call.bot, call.message.chat.id, "trip_msg_ids")
    with suppress(TelegramBadRequest): await call.message.delete()
    
    history = get_driver_history(call.from_user.id)
    msg_ids = []

    if not history:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="drv_my_trips")]])
        m = await call.message.answer("📜 <b>Історія порожня.</b>", reply_markup=kb, parse_mode="HTML")
        msg_ids.append(m.message_id)
    else:
        h = await call.message.answer("📜 <b>Ваші останні поїздки:</b>", parse_mode="HTML")
        msg_ids.append(h.message_id)
        
        for t in history:
            status_icon = "✅" if t['status'] == 'finished' else "❌"
            txt = (
                f"{status_icon} <b>{t['origin']} ➝ {t['destination']}</b>\n"
                f"📅 {t['date']} | 💰 {t['price']} грн\n"
                f"💺 {t['seats_taken']}/{t['seats_total']} місць"
            )
            m = await call.message.answer(txt, parse_mode="HTML")
            msg_ids.append(m.message_id)
            
        f = await call.message.answer("🔽 Меню:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Активні поїздки", callback_data="drv_my_trips")]]))
        msg_ids.append(f.message_id)
        
    await state.update_data(trip_msg_ids=msg_ids)


@router.callback_query(F.data.startswith("drv_finish_"))
async def driver_finish_trip_handler(call: types.CallbackQuery, state: FSMContext):
    trip_id = call.data.split("_")[2]
    passengers = get_trip_passengers(trip_id)
    finish_trip(trip_id)
    await call.answer("Поїздку завершено!", show_alert=True)
    await show_driver_trips(call, state)
    if passengers: await ask_for_ratings(call.bot, trip_id, call.from_user.id, passengers)

@router.callback_query(F.data.startswith("kick_"))
async def kick_passenger_handler(call: types.CallbackQuery, state: FSMContext):
    info = kick_passenger(int(call.data.split("_")[1]), call.from_user.id)
    if info:
        await call.answer("Пасажира висаджено.")
        with suppress(Exception): await call.bot.send_message(info['passenger_id'], "🚫 Водій скасував ваше бронювання.")
        await show_driver_trips(call, state)

@router.callback_query(F.data.startswith("drv_ask_cancel_"))
async def ask_cancel(call: types.CallbackQuery):
    tid = call.data.split("_")[3]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Так, скасувати", callback_data=f"drv_do_cancel_{tid}")],
        [InlineKeyboardButton(text="🔙 Ні", callback_data="drv_my_trips")]
    ])
    await call.message.edit_text("⚠️ <b>Скасувати поїздку?</b>\nПасажири отримають сповіщення.", reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data.startswith("drv_do_cancel_"))
async def do_cancel(call: types.CallbackQuery, state: FSMContext):
    trip_info, passengers = cancel_trip_full(call.data.split("_")[3], call.from_user.id)
    await call.answer("Поїздку скасовано.")
    for pid in passengers:
        with suppress(Exception): await call.bot.send_message(pid, f"⚠️ Водій скасував поїздку {trip_info['origin']} - {trip_info['destination']}.")
    await show_driver_trips(call, state)
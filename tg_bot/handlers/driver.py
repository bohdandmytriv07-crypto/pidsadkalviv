import uuid
import re
from contextlib import suppress
from aiogram import Router, F, types, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

# Імпорти бази даних
from database import (
    get_user, save_user, create_trip, get_driver_active_trips, 
    get_trip_passengers, cancel_trip_full, kick_passenger, 
    get_last_driver_trip, get_subscribers_for_trip,
    add_or_update_city, finish_trip  
)
from handlers.rating import ask_for_ratings 

from states import TripStates
from keyboards import kb_back, kb_dates, kb_menu
from utils import (
    clean_user_input, delete_prev_msg, update_or_send_msg, 
    is_valid_city, validate_city_real, get_city_suggestion,
    delete_messages_list  # 🔥 Додано для очищення списку поїздок
)

router = Router()

# ==========================================
# 🚗 СТВОРЕННЯ ПОЇЗДКИ
# ==========================================

@router.callback_query(F.data == "drv_create")
async def start_create_trip_handler(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    menu_msg_id = call.message.message_id
    await state.clear()
    await state.update_data(last_msg_id=menu_msg_id, role="driver")
    await call.answer()
    
    user_id = call.from_user.id
    user = get_user(user_id)
    
    if not user:
        save_user(user_id, call.from_user.full_name, "-")
        user = get_user(user_id)

    has_phone = user['phone'] and user['phone'] != "-"
    has_car = user['model'] and user['model'] != "-"
    
    if not has_phone or not has_car:
        text = (
            "⚠️ <b>Ви не можете створити поїздку.</b>\n\n"
            "Водій повинен мати заповнений профіль:\n"
            "1. Номер телефону\n"
            "2. Марка та номер авто\n\n"
            "Натисніть кнопку нижче, щоб додати дані."
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👤 Мій профіль / Редагувати", callback_data="profile_edit")],
            [InlineKeyboardButton(text="🔙 В меню", callback_data="menu_home")]
        ])
        await update_or_send_msg(bot, call.message.chat.id, state, text, keyboard)
        return

    last_trip = get_last_driver_trip(user_id)
    
    if last_trip:
        trip_details = (
            f"🔄 <b>Створити як минулого разу?</b>\n\n"
            f"🚗 Маршрут: <b>{last_trip['origin']} ➝ {last_trip['destination']}</b>\n"
            f"💰 Ціна: {last_trip['price']} грн\n"
            f"💺 Місць: {last_trip['seats_total']}\n\n"
            f"<i>Ми запитаємо тільки нову дату та час.</i>"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚡️ Так, повторити", callback_data="drv_repeat_last")],
            [InlineKeyboardButton(text="🆕 Ні, новий маршрут", callback_data="drv_new_route")],
            [InlineKeyboardButton(text="🔙 Скасувати", callback_data="menu_home")]
        ])
        await update_or_send_msg(bot, call.message.chat.id, state, trip_details, keyboard)
    else:
        await _start_new_trip_questions(call.message, state, bot)


@router.callback_query(F.data == "drv_new_route")
async def new_route_selected(call: types.CallbackQuery, state: FSMContext):
    await _start_new_trip_questions(call.message, state, call.bot)


@router.callback_query(F.data == "drv_repeat_last")
async def repeat_route_selected(call: types.CallbackQuery, state: FSMContext):
    last_trip = get_last_driver_trip(call.from_user.id)
    
    if not last_trip:
        await call.answer("Помилка: поїздку не знайдено", show_alert=True)
        await _start_new_trip_questions(call.message, state, call.bot)
        return

    await state.update_data(
        origin=last_trip['origin'],
        destination=last_trip['destination'],
        seats=str(last_trip['seats_total']),
        saved_price=last_trip['price']
    )

    await state.set_state(TripStates.date)
    await update_or_send_msg(
        call.bot, call.message.chat.id, state,
        "📅 <b>Дата нової поїздки?</b>", 
        kb_dates("tripdate")
    )


async def _start_new_trip_questions(message: types.Message, state: FSMContext, bot: Bot):
    await state.set_state(TripStates.origin)
    await update_or_send_msg(
        bot, message.chat.id, state,
        "📍 <b>Звідки виїжджаємо?</b>\nВведіть місто (напр. Київ):", 
        kb_back()
    )


# --- FSM: КРОКИ ВВЕДЕННЯ ДАНИХ ---

@router.message(TripStates.origin)
async def process_origin(message: types.Message, state: FSMContext, bot: Bot):
    await clean_user_input(message)
    raw_text = message.text.strip()
    
    suggestion = get_city_suggestion(raw_text)
    
    if suggestion:
        clean_city = suggestion
    else:
        msg_wait = await message.answer("🌍 Перевіряю назву міста...")
        real_name = validate_city_real(raw_text)
        with suppress(TelegramBadRequest): await msg_wait.delete()

        if real_name:
            clean_city = real_name
            add_or_update_city(clean_city)
        else:
            await update_or_send_msg(
                bot, message.chat.id, state,
                f"❌ <b>Місто '{raw_text}' не знайдено!</b>\nСпробуйте ще раз або введіть найближче велике місто.",
                kb_back()
            )
            return

    await state.update_data(origin=clean_city)
    await state.set_state(TripStates.destination)
    
    await update_or_send_msg(
        bot, message.chat.id, state,
        f"✅ Звідки: <b>{clean_city}</b>\n\n🏁 <b>Куди їдемо?</b>\nВведіть місто:", 
        kb_back()
    )


@router.message(TripStates.destination)
async def process_destination(message: types.Message, state: FSMContext, bot: Bot):
    await clean_user_input(message)
    raw_text = message.text.strip()

    suggestion = get_city_suggestion(raw_text)
    
    if suggestion:
        clean_city = suggestion
    else:
        msg_wait = await message.answer("🌍 Перевіряю назву міста...")
        real_name = validate_city_real(raw_text)
        with suppress(TelegramBadRequest): await msg_wait.delete()

        if real_name:
            clean_city = real_name
            add_or_update_city(clean_city)
        else:
            await update_or_send_msg(
                bot, message.chat.id, state,
                f"❌ <b>Місто '{raw_text}' не знайдено!</b>\nСпробуйте ще раз.",
                kb_back()
            )
            return
    
    await state.update_data(destination=clean_city)
    await state.set_state(TripStates.date)
    
    await update_or_send_msg(
        bot, message.chat.id, state,
        "📅 <b>Коли плануєте поїздку?</b>", 
        kb_dates("tripdate")
    )


@router.callback_query(TripStates.date)
async def process_date(call: types.CallbackQuery, state: FSMContext):
    date_val = call.data.split("_")[1]
    await state.update_data(date=date_val)
    
    await state.set_state(TripStates.time)
    await update_or_send_msg(
        call.bot, call.message.chat.id, state,
        f"📅 Дата: {date_val}\n\n🕒 <b>Введіть час виїзду:</b>\nФормат ГГ:ХХ (напр. 18:30)", 
        kb_back()
    )


@router.message(TripStates.time)
async def process_time(message: types.Message, state: FSMContext, bot: Bot):
    await clean_user_input(message)
    
    if not re.match(r"^([01]\d|2[0-3]):([0-5]\d)$", message.text):
        await update_or_send_msg(
            bot, message.chat.id, state,
            "⚠️ <b>Невірний формат часу!</b>\n\n🕒 <b>Введіть час ще раз:</b>\nФормат ГГ:ХХ (напр. 18:30)",
            kb_back()
        )
        return

    await state.update_data(time=message.text)
    data = await state.get_data()
    
    if data.get('saved_price'):
        await finalize_trip_creation(message, state, bot, price_override=data.get('saved_price'))
        return

    await state.set_state(TripStates.seats)
    await update_or_send_msg(
        bot, message.chat.id, state,
        "💺 <b>Скільки вільних місць?</b>\nВведіть цифру (від 1 до 8):", 
        kb_back()
    )


@router.message(TripStates.seats)
async def process_seats(message: types.Message, state: FSMContext, bot: Bot):
    await clean_user_input(message)
    text = message.text.strip()
    
    if not text.isdigit() or not (1 <= int(text) <= 8):
        await update_or_send_msg(
            bot, message.chat.id, state,
            "⚠️ <b>Помилка!</b>\n💺 <b>Введіть кількість місць цифрою:</b>\nДозволено від 1 до 8.",
            kb_back()
        )
        return

    await state.update_data(seats=int(text))
    await state.set_state(TripStates.price)
    
    await update_or_send_msg(
        bot, message.chat.id, state,
        "💰 <b>Вкажіть ціну за 1 місце (грн):</b>\nНапишіть суму цифрами:", 
        kb_back()
    )


@router.message(TripStates.price)
async def finalize_trip_creation(message: types.Message, state: FSMContext, bot: Bot, price_override=None):
    if price_override:
        final_price = int(price_override)
    else:
        await clean_user_input(message)
        try:
            final_price = int(message.text)
        except ValueError:
            await update_or_send_msg(
                bot, message.chat.id, state, 
                "⚠️ <b>Ціна має бути числом!</b>\n💰 Введіть ціну:", 
                kb_back()
            )
            return

    if final_price <= 0:
        await update_or_send_msg(
            bot, message.chat.id, state,
            "⚠️ <b>Ціна має бути більше 0!</b>\n💰 <b>Вкажіть вартість поїздки (грн):</b>",
            kb_back()
        )
        return 

    data = await state.get_data()
    
    trip_id = str(uuid.uuid4())[:8]
    create_trip(
        trip_id, message.from_user.id, 
        data['origin'], data['destination'], 
        data['date'], data['time'], 
        int(data['seats']), int(final_price)
    )
    
    add_or_update_city(data['origin'])
    add_or_update_city(data['destination'])

    kb_return = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Повернутися в меню", callback_data="menu_home")]
    ])

    success_text = (
        f"✅ <b>Поїздку створено!</b>\n\n"
        f"🚗 {data['origin']} -> {data['destination']}\n"
        f"📅 {data['date']} | 🕒 {data['time']}\n"
        f"💰 {final_price} грн"
    )

    await update_or_send_msg(bot, message.chat.id, state, success_text, kb_return)
    
    last_msg_id = data.get('last_msg_id')
    await state.clear()
    await state.update_data(role="driver", last_msg_id=last_msg_id)
    
    await _notify_subscribers(bot, message.from_user.id, trip_id, data, final_price)


async def _notify_subscribers(bot, driver_id, trip_id, trip_data, price):
    subscribers = get_subscribers_for_trip(trip_data['origin'], trip_data['destination'], trip_data['date'])
    if not subscribers: return

    text = (
        f"🔔 <b>Знайдено поїздку!</b>\n"
        f"🚗 {trip_data['origin']} ➝ {trip_data['destination']}\n"
        f"📅 {trip_data['date']} | ⏰ {trip_data['time']}\n"
        f"💰 {price} грн\n"
        f"Швидше бронюйте!"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Бронювати місце", callback_data=f"book_{trip_id}")],
        [InlineKeyboardButton(text="💬 Написати водію", callback_data=f"chat_start_{driver_id}")]
    ])
    
    count = 0
    for sub_id in subscribers:
        if sub_id == driver_id: continue
        try:
            await bot.send_message(sub_id, text, reply_markup=keyboard, parse_mode="HTML")
            count += 1
        except Exception: pass
            
    if count > 0:
        with suppress(Exception):
            await bot.send_message(driver_id, f"ℹ️ Ми повідомили {count} людей, які шукали цей маршрут.")


# ==========================================
# 🗂 МОЇ ПОЇЗДКИ (КЕРУВАННЯ)
# ==========================================

@router.callback_query(F.data == "drv_my_trips")
async def show_driver_trips(call: types.CallbackQuery, state: FSMContext):
    # 🔥 ВИДАЛЯЄМО СТАРІ КАРТКИ, ЯКЩО ВОНИ Є
    await delete_messages_list(state, call.bot, call.message.chat.id, "trip_msg_ids")
    
    # Видаляємо саме меню (щоб було чисто)
    with suppress(TelegramBadRequest):
        await call.message.delete()

    trips = get_driver_active_trips(call.from_user.id)
    new_msg_ids = []

    if not trips:
        kb_empty = InlineKeyboardMarkup(inline_keyboard=[
             [InlineKeyboardButton(text="🔙 Повернутися в меню", callback_data="menu_home")]
        ])
        msg = await call.message.answer(
            "🗂 <b>У вас немає активних поїздок.</b>", 
            reply_markup=kb_empty, 
            parse_mode="HTML"
        )
        new_msg_ids.append(msg.message_id)
        await state.update_data(trip_msg_ids=new_msg_ids)
        return

    header_msg = await call.message.answer("🗂 <b>Ваші активні поїздки:</b>", parse_mode="HTML")
    new_msg_ids.append(header_msg.message_id)

    for trip in trips:
        free_seats = trip['seats_total'] - trip['seats_taken']
        card_text = (
            f"🚗 <b>{trip['origin']} ➝ {trip['destination']}</b>\n"
            f"📅 {trip['date']} | ⏰ {trip['time']}\n"
            f"💰 {trip['price']} грн | 💺 Вільно: {free_seats}"
        )
        
        passengers = get_trip_passengers(trip['id'])
        keyboard_rows = []
        
        if passengers:
            card_text += "\n\n👥 <b>Пасажири:</b>"
            for p in passengers:
                card_text += f"\n👤 {p['name']} (<code>{p['phone']}</code>)"
                keyboard_rows.append([
                    InlineKeyboardButton(text=f"💬 Чат: {p['name']}", callback_data=f"chat_start_{p['user_id']}"),
                    InlineKeyboardButton(text="🚫 Висадити", callback_data=f"kick_{p['booking_id']}")
                ])
        else:
            card_text += "\n\n<i>Пасажирів поки немає.</i>"

        # 🔥 КНОПКА ЗАВЕРШЕННЯ ПОЇЗДКИ 🔥
        keyboard_rows.append([
            InlineKeyboardButton(text="🏁 Завершити і оцінити", callback_data=f"drv_finish_{trip['id']}")
        ])

        keyboard_rows.append([InlineKeyboardButton(text="❌ Скасувати цю поїздку", callback_data=f"drv_ask_cancel_{trip['id']}")])
        
        card_msg = await call.message.answer(card_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_rows), parse_mode="HTML")
        new_msg_ids.append(card_msg.message_id)

    kb_back_btn = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад в меню", callback_data="menu_home")]])
    back_msg = await call.message.answer("🔽 Управління:", reply_markup=kb_back_btn)
    new_msg_ids.append(back_msg.message_id)

    await state.update_data(trip_msg_ids=new_msg_ids)


# --- ЗАВЕРШЕННЯ ПОЇЗДКИ ТА РЕЙТИНГ (НОВЕ) ---

@router.callback_query(F.data.startswith("drv_finish_"))
async def driver_finish_trip_handler(call: types.CallbackQuery, state: FSMContext):
    trip_id = call.data.split("_")[2]
    
    # 1. Отримуємо пасажирів (поки поїздка ще активна)
    passengers = get_trip_passengers(trip_id)
    
    # 2. Закриваємо поїздку в БД
    finish_trip(trip_id)
    
    # Показуємо алерт, що все ок
    await call.answer("🏁 Поїздку успішно завершено!", show_alert=True)
    
    # 3. 🔥 ПЕРЕМАЛЬОВУЄМО СПИСОК ПОЇЗДОК
    # Це автоматично видалить стару картку і покаже оновлений список (без цієї поїздки)
    await show_driver_trips(call, state)
        
    # 4. Запускаємо процес оцінювання (фоново)
    if passengers:
        # Ця функція розішле повідомлення всім пасажирам і водію
        await ask_for_ratings(call.bot, trip_id, call.from_user.id, passengers)


# --- ВИСАДКА ПАСАЖИРА ---

@router.callback_query(F.data.startswith("kick_"))
async def kick_passenger_handler(call: types.CallbackQuery, state: FSMContext):
    try:
        booking_id = int(call.data.split("_")[1])
    except (ValueError, IndexError):
        await call.answer("Помилка даних", show_alert=True)
        return

    info = kick_passenger(booking_id, call.from_user.id)
    
    if info:
        await call.answer("✅ Пасажира висаджено.", show_alert=True)
        
        msg_text = (
            f"🚫 <b>Вас було знято з рейсу.</b>\n"
            f"Водій скасував ваше бронювання.\n"
            f"🚗 {info['origin']} ➝ {info['destination']}\n"
            f"📅 {info['date']} о {info['time']}"
        )
        with suppress(Exception):
            await call.bot.send_message(chat_id=info['passenger_id'], text=msg_text, parse_mode="HTML")

        # Оновлюємо список
        await show_driver_trips(call, state)
    else:
        await call.answer("❌ Помилка: не вдалося висадити.", show_alert=True)


# --- СКАСУВАННЯ ПОЇЗДКИ (З ПІДТВЕРДЖЕННЯМ) ---

@router.callback_query(F.data.startswith("drv_ask_cancel_"))
async def ask_cancel_trip_handler(call: types.CallbackQuery):
    trip_id = call.data.split("_")[3]
    
    confirm_text = (
        "⚠️ <b>Ви впевнені, що хочете скасувати цю поїздку?</b>\n\n"
        "Цю дію неможливо відмінити. Пасажири отримають сповіщення."
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Так, скасувати", callback_data=f"drv_do_cancel_{trip_id}")],
        [InlineKeyboardButton(text="🔙 Ні, залишити", callback_data="drv_my_trips")]
    ])
    
    # Редагуємо текст картки на підтвердження
    await call.message.edit_text(confirm_text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(F.data.startswith("drv_do_cancel_"))
async def perform_cancel_trip_handler(call: types.CallbackQuery, state: FSMContext):
    trip_id = call.data.split("_")[3]
    
    trip_info, passengers_to_notify = cancel_trip_full(trip_id, call.from_user.id)
    
    if trip_info:
        await call.answer("✅ Поїздку скасовано.", show_alert=True)
        
        msg_text = (
            f"⚠️ <b>Увага! Водій скасував поїздку.</b>\n"
            f"🚗 {trip_info['origin']} ➝ {trip_info['destination']}\n"
            f"📅 {trip_info['date']} о {trip_info['time']}\n"
            f"Будь ласка, знайдіть інший варіант."
        )
        
        for pass_id in passengers_to_notify:
            with suppress(Exception):
                await call.bot.send_message(chat_id=pass_id, text=msg_text, parse_mode="HTML")
        
        # Оновлюємо список (це видалить повідомлення підтвердження)
        await show_driver_trips(call, state)
    else:
        await call.answer("❌ Помилка: поїздка не знайдена.", show_alert=True)
        await show_driver_trips(call, state)
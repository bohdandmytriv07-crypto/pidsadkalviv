import os
import sqlite3
from contextlib import suppress
from aiogram import Router, F, types, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.exceptions import TelegramBadRequest

# Імпорти з твого проекту
from database import (
    get_connection, 
    get_stats_general, 
    get_top_routes, 
    get_conversion_rate
)
from config import DB_FILE, ADMIN_IDS

router = Router()

class AdminStates(StatesGroup):
    broadcast = State()
    ban_user = State()


# ==========================================
# 🛠 ДОПОМІЖНА ФУНКЦІЯ (DASHBOARD)
# ==========================================

async def render_admin_dashboard(message: types.Message, edit: bool = False):
    """
    Малює головне меню адміна. 
    edit=True -> редагує старе повідомлення.
    edit=False -> надсилає нове.
    """
    stats = get_stats_general()
    
    passengers_count = stats['total_users'] - stats['total_drivers']

    stats_text = (
        f"👮‍♂️ <b>Панель керування</b>\n\n"
        f"👥 Всього юзерів: <b>{stats['total_users']}</b>\n"
        f"🚖 Водіїв: <b>{stats['total_drivers']}</b> | 🚶 Пасажирів: <b>{passengers_count}</b>\n"
        f"🚗 Активних поїздок: <b>{stats['active_trips']}</b>\n"
        f"🏁 Завершених: <b>{stats['finished_trips']}</b>\n"
        f"🎫 Всього бронювань: <b>{stats['total_bookings']}</b>"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Розширена статистика", callback_data="admin_stats_full")],
        [InlineKeyboardButton(text="📋 Активні поїздки (Топ-10)", callback_data="admin_active_trips")],
        [InlineKeyboardButton(text="📢 Розсилка всім", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="🚫 Бан/Розбан користувача", callback_data="admin_ban_menu")],
        [InlineKeyboardButton(text="💾 Скачати БД (Backup)", callback_data="admin_export_db")]
    ])

    if edit:
        try:
            await message.edit_text(stats_text, reply_markup=kb, parse_mode="HTML")
        except TelegramBadRequest:
            await message.delete()
            await message.answer(stats_text, reply_markup=kb, parse_mode="HTML")
    else:
        await message.answer(stats_text, reply_markup=kb, parse_mode="HTML")


# ==========================================
# 🏠 ГОЛОВНЕ МЕНЮ
# ==========================================

@router.message(Command("admin"))
async def admin_start_command(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    
    with suppress(TelegramBadRequest):
        await message.delete()
        
    await state.clear()
    await render_admin_dashboard(message, edit=False)

@router.callback_query(F.data == "admin_back_home")
async def admin_back_home(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS: return
    await state.clear()
    await render_admin_dashboard(call.message, edit=True)


# ==========================================
# 📊 СТАТИСТИКА (НОВЕ!)
# ==========================================

@router.callback_query(F.data == "admin_stats_full")
async def show_full_stats(call: types.CallbackQuery):
    if call.from_user.id not in ADMIN_IDS: return

    # Отримуємо розширені дані
    general = get_stats_general()
    top_routes = get_top_routes(5)
    conversion = get_conversion_rate()

    text = (
        f"📊 <b>ДЕТАЛЬНА СТАТИСТИКА</b>\n"
        f"➖➖➖➖➖➖➖➖\n\n"
        f"📈 <b>Ефективність:</b>\n"
        f"• Конверсія (Пошук -> Бронь): <b>{conversion}%</b>\n\n"
        f"🔥 <b>ТОП-5 Маршрутів (Попит):</b>\n"
    )

    if top_routes:
        for i, row in enumerate(top_routes, 1):
            text += f"{i}. {row['origin']} ➝ {row['destination']}: <b>{row['cnt']}</b> пошуків\n"
    else:
        text += "<i>Даних поки що недостатньо...</i>"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back_home")]
    ])
    
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


# ==========================================
# 📋 ПЕРЕГЛЯД ПОЇЗДОК
# ==========================================

@router.callback_query(F.data == "admin_active_trips")
async def show_active_trips_handler(call: types.CallbackQuery):
    if call.from_user.id not in ADMIN_IDS: return
    
    conn = get_connection()
    cursor = conn.cursor()
    query = """
        SELECT t.origin, t.destination, t.date, t.time, t.price, t.seats_taken, t.seats_total,
               u.name, u.phone
        FROM trips t
        JOIN users u ON t.user_id = u.user_id
        WHERE t.status = 'active'
        ORDER BY t.rowid DESC LIMIT 10
    """
    rows = cursor.execute(query).fetchall()
    conn.close()

    if not rows:
        await call.answer("📭 Активних поїздок немає.", show_alert=True)
        return

    text = "📋 <b>Активні поїздки (Топ-10):</b>\n\n"
    for row in rows:
        text += (
            f"🚗 <b>{row['origin']} -> {row['destination']}</b>\n"
            f"📅 {row['date']} {row['time']} | 💰 {row['price']} грн\n"
            f"👤 {row['name']} (<code>{row['phone']}</code>)\n"
            f"💺 {row['seats_taken']}/{row['seats_total']}\n"
            f"➖➖➖➖➖➖\n"
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back_home")]
    ])
    
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


# ==========================================
# 🚫 БАН / РОЗБАН
# ==========================================

@router.callback_query(F.data == "admin_ban_menu")
async def ban_menu_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS: return

    text = (
        "🚫 <b>Режим блокування</b>\n\n"
        "Надішліть <b>ID користувача</b> (тільки цифри) або перешліть його повідомлення сюди."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Скасувати", callback_data="admin_back_home")]
    ])
    
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await state.update_data(menu_msg_id=call.message.message_id)
    await state.set_state(AdminStates.ban_user)


@router.message(AdminStates.ban_user)
async def process_ban_user(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return

    with suppress(TelegramBadRequest):
        await message.delete()

    target_id = None
    if message.forward_from:
        target_id = message.forward_from.id
    elif message.text and message.text.strip().isdigit():
        target_id = int(message.text.strip())

    data = await state.get_data()
    menu_msg_id = data.get("menu_msg_id")

    if not target_id:
        return

    result_text = ""
    conn = get_connection()
    cursor = conn.cursor()
    
    user_data = cursor.execute("SELECT name, is_banned FROM users WHERE user_id = ?", (target_id,)).fetchone()

    if not user_data:
        result_text = f"❌ Користувача <b>{target_id}</b> не знайдено в базі."
    else:
        new_status = 0 if user_data['is_banned'] else 1
        cursor.execute("UPDATE users SET is_banned = ? WHERE user_id = ?", (new_status, target_id))
        conn.commit()
        
        status_str = "ЗАБАНЕНО 🔴" if new_status else "РОЗБАНЕНО 🟢"
        result_text = f"✅ Користувача <b>{user_data['name']}</b> було {status_str}"

        if new_status:
            with suppress(Exception):
                await message.bot.send_message(target_id, "⛔ <b>Ваш акаунт заблоковано адміністратором.</b>", parse_mode="HTML")
    
    conn.close()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="admin_back_home")]
    ])
    
    if menu_msg_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id, 
                message_id=menu_msg_id, 
                text=result_text, 
                reply_markup=kb, 
                parse_mode="HTML"
            )
        except:
            await message.answer(result_text, reply_markup=kb, parse_mode="HTML")
    
    await state.clear()


# ==========================================
# 📢 РОЗСИЛКА
# ==========================================

@router.callback_query(F.data == "admin_broadcast")
async def start_broadcast_handler(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS: return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Скасувати", callback_data="admin_back_home")]
    ])
    await call.message.edit_text("✍️ <b>Напишіть текст (або надішліть фото) для розсилки:</b>", reply_markup=kb, parse_mode="HTML")
    
    await state.update_data(menu_msg_id=call.message.message_id)
    await state.set_state(AdminStates.broadcast)


@router.message(AdminStates.broadcast)
async def perform_broadcast(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return

    data = await state.get_data()
    menu_msg_id = data.get("menu_msg_id")

    # Копіюємо повідомлення для розсилки, оригінал видаляємо (адміна)
    msg_to_send = message
    
    # Статус
    if menu_msg_id:
        with suppress(Exception):
            await message.bot.edit_message_text(
                chat_id=message.chat.id, 
                message_id=menu_msg_id, 
                text="⏳ <b>Розсилка запущена... Це може зайняти час.</b>", 
                parse_mode="HTML"
            )

    conn = get_connection()
    users = conn.execute("SELECT user_id FROM users").fetchall()
    conn.close()

    good, bad = 0, 0
    for u in users:
        try:
            await msg_to_send.copy_to(chat_id=u['user_id'])
            good += 1
        except:
            bad += 1

    report = (
        f"✅ <b>Розсилку завершено!</b>\n\n"
        f"📨 Надіслано: {good}\n"
        f"💀 Заблоковано/Помилки: {bad}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 В головне меню", callback_data="admin_back_home")]
    ])

    if menu_msg_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id, 
                message_id=menu_msg_id, 
                text=report, 
                reply_markup=kb, 
                parse_mode="HTML"
            )
        except:
            await message.answer(report, reply_markup=kb, parse_mode="HTML")
            
    await state.clear()


# ==========================================
# 💾 BACKUP БД
# ==========================================

@router.callback_query(F.data == "admin_export_db")
async def export_database_handler(call: types.CallbackQuery):
    if call.from_user.id not in ADMIN_IDS: return
    
    if os.path.exists(DB_FILE):
        await call.message.answer_document(FSInputFile(DB_FILE), caption=f"📦 Backup від {os.path.getmtime(DB_FILE)}")
    else:
        await call.answer("Файл бази даних не знайдено!", show_alert=True)
    await call.answer()
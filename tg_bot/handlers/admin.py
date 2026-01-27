import os
import asyncio
from contextlib import suppress
from aiogram import Router, F, types, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.exceptions import TelegramBadRequest

# Імпорти з бази даних
from database import (
    get_connection, get_stats_extended, get_stats_general, 
    get_top_routes, get_conversion_rate, get_financial_stats,
    get_peak_hours, get_top_failed_searches, get_top_sources
)
from config import DB_FILE, ADMIN_IDS

router = Router()

class AdminStates(StatesGroup):
    broadcast = State()
    ban_user = State()

# ==========================================
# 🏠 ГОЛОВНИЙ ДАШБОРД (SNAPSHOT)
# ==========================================

async def render_admin_dashboard(message: types.Message, edit: bool = False):
    """Головна сторінка: стан системи на поточну хвилину."""
    
    # 1. Загальні цифри (База)
    gen_stats = get_stats_general()
    
    # 2. Активність (Живі юзери)
    ext_stats = get_stats_extended()
    
    # 3. Фінанси (Орієнтовні)
    total_gmv = get_financial_stats()

    # Формуємо красивий текст
    text = (
        f"👨‍💻 <b>ПАНЕЛЬ АДМІНІСТРАТОРА</b>\n"
        f"<i>Стан проекту на зараз</i>\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"👥 <b>Аудиторія:</b>\n"
        f"• Всього в базі: <b>{ext_stats['total_users']}</b>\n"
        f"• Нових за сьогодні: <b>+{ext_stats['new_today']}</b>\n"
        f"• Живих сьогодні (DAU): <b>{ext_stats['dau']}</b>\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"🚗 <b>Поїздки:</b>\n"
        f"• Активних зараз: <b>{gen_stats['active_trips']}</b> 🟢\n"
        f"• Завершених: <b>{gen_stats['finished_trips']}</b>\n"
        f"• Бронювань місць: <b>{gen_stats['total_bookings']}</b>\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"💰 <b>Обіг (GMV):</b> <code>{total_gmv} грн</code>"
    )

    # Кнопки навігації
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📈 Маркетинг та Люди", callback_data="admin_stats_users"),
            InlineKeyboardButton(text="🛒 Продукт та Попит", callback_data="admin_stats_product")
        ],
        [InlineKeyboardButton(text="📋 Список активних поїздок", callback_data="admin_active_trips")],
        [InlineKeyboardButton(text="📢 Зробити розсилку", callback_data="admin_broadcast")],
        [
            InlineKeyboardButton(text="🚫 Банхаммер", callback_data="admin_ban_menu"),
            InlineKeyboardButton(text="💾 Скачати БД", callback_data="admin_export_db")
        ],
        [InlineKeyboardButton(text="🔄 Оновити дані", callback_data="admin_back_home")]
    ])

    if edit:
        try: await message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except: await message.delete(); await message.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.message(Command("admin"))
async def admin_start_command(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    with suppress(TelegramBadRequest): await message.delete()
    await state.clear()
    await render_admin_dashboard(message, edit=False)

@router.callback_query(F.data == "admin_back_home")
async def admin_back_home(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS: return
    await state.clear()
    await render_admin_dashboard(call.message, edit=True)


# ==========================================
# 📈 СТАТИСТИКА 1: МАРКЕТИНГ І ЛЮДИ
# ==========================================

@router.callback_query(F.data == "admin_stats_users")
async def show_users_stats(call: types.CallbackQuery):
    if call.from_user.id not in ADMIN_IDS: return

    stats = get_stats_extended()
    
    # Джерела трафіку
    top_sources = get_top_sources()
    sources_text = ""
    if top_sources:
        for src, count in top_sources:
            sources_text += f"├ 🔗 {src}: <b>{count}</b>\n"
    else:
        sources_text = "├ (немає даних про рефералів)\n"

    # Retention Rate
    retention = 0
    if stats['total_users'] > 0:
        retention = round((stats['mau'] / stats['total_users']) * 100, 1)

    text = (
        f"📈 <b>МАРКЕТИНГ ТА АУДИТОРІЯ</b>\n"
        f"➖➖➖➖➖➖➖➖➖➖\n\n"
        f"<b>📊 Залучення (Traffic Sources):</b>\n"
        f"{sources_text}"
        f"└ <i>Решта: прямий вхід / пошук</i>\n\n"
        
        f"<b>💀 Відтік (Churn):</b>\n"
        f"• Заблокували бота: <b>{stats['blocked']}</b> людей\n"
        f"• Це <b>{round((stats['blocked'] / stats['total_users'] * 100), 1)}%</b> від усіх юзерів\n\n"
        
        f"<b>❤️ Лояльність (Retention):</b>\n"
        f"• MAU (Заходили за 30 днів): <b>{stats['mau']}</b>\n"
        f"• Коефіцієнт утримання: <b>{retention}%</b>\n"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back_home")]])
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


# ==========================================
# 🛒 СТАТИСТИКА 2: ПРОДУКТ І ПОПИТ
# ==========================================

@router.callback_query(F.data == "admin_stats_product")
async def show_product_stats(call: types.CallbackQuery):
    if call.from_user.id not in ADMIN_IDS: return

    conversion = get_conversion_rate()
    peaks = get_peak_hours()
    failed_searches = get_top_failed_searches()
    top_routes = get_top_routes(3)

    text = (
        f"🛒 <b>ПРОДУКТ ТА ПОПИТ</b>\n"
        f"➖➖➖➖➖➖➖➖➖➖\n\n"
        f"<b>🎯 Воронка продажів:</b>\n"
        f"• Конверсія (Пошук ➝ Бронь): <b>{conversion}%</b>\n\n"
        
        f"<b>📉 Втрачений попит (Шукали, але пусто):</b>\n"
    )
    
    if failed_searches:
        for row in failed_searches:
            text += f"• {row['event_data']} — <b>{row['cnt']}</b> запитів\n"
        text += f"<i>👉 Шукайте водіїв на ці напрямки!</i>\n\n"
    else:
        text += "✅ <i>Всі пошуки успішні.</i>\n\n"

    text += "<b>🔥 Найпопулярніші маршрути:</b>\n"
    if top_routes:
        for row in top_routes:
            text += f"• {row['origin']} ➝ {row['destination']} (<b>{row['cnt']}</b>)\n"
    else:
        text += "— Немає даних\n"
        
    text += "\n<b>⏰ Години пік (Топ активності):</b>\n"
    if peaks:
        times = [f"{row['hour']}:00" for row in peaks]
        text += ", ".join(times)
    else:
        text += "— Немає даних"

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back_home")]])
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


# ==========================================
# 📋 ПЕРЕГЛЯД ПОЇЗДОК
# ==========================================

@router.callback_query(F.data == "admin_active_trips")
async def show_active_trips_handler(call: types.CallbackQuery):
    if call.from_user.id not in ADMIN_IDS: return
    
    conn = get_connection()
    rows = conn.execute("SELECT t.origin, t.destination, t.date, t.time, t.price, t.seats_taken, t.seats_total, u.name, u.phone, u.username FROM trips t JOIN users u ON t.user_id = u.user_id WHERE t.status = 'active' ORDER BY t.rowid DESC LIMIT 10").fetchall()
    conn.close()

    if not rows:
        await call.answer("📭 Активних поїздок немає.", show_alert=True)
        return

    text = "📋 <b>Останні 10 активних поїздок:</b>\n\n"
    for row in rows:
        uname = f"@{row['username']}" if row['username'] else "без юзернейму"
        text += (
            f"🚗 <b>{row['origin']} ➝ {row['destination']}</b>\n"
            f"📅 {row['date']} {row['time']} | 💰 <b>{row['price']} грн</b>\n"
            f"👤 {row['name']} ({uname})\n"
            f"📞 <code>{row['phone']}</code>\n"
            f"💺 Зайнято: <b>{row['seats_taken']}/{row['seats_total']}</b>\n"
            f"➖➖➖➖➖➖\n"
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back_home")]])
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


# ==========================================
# 🚫 БАН / РОЗБАН
# ==========================================

@router.callback_query(F.data == "admin_ban_menu")
async def ban_menu_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS: return

    text = (
        "🚫 <b>Режим блокування</b>\n\n"
        "1. Надішліть <b>ID користувача</b> (тільки цифри)\n"
        "2. Або перешліть сюди його повідомлення."
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

    conn = get_connection()
    user_data = conn.execute("SELECT name, is_banned, username FROM users WHERE user_id = ?", (target_id,)).fetchone()

    if not user_data:
        result_text = f"❌ Користувача <b>{target_id}</b> не знайдено в базі."
    else:
        new_status = 0 if user_data['is_banned'] else 1
        conn.execute("UPDATE users SET is_banned = ? WHERE user_id = ?", (new_status, target_id))
        conn.commit()
        
        status_str = "ЗАБАНЕНО 🔴" if new_status else "РОЗБАНЕНО 🟢"
        uname = f"(@{user_data['username']})" if user_data['username'] else ""
        result_text = f"✅ Користувача <b>{user_data['name']}</b> {uname} було {status_str}"

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

    msg_to_send = message
    
    if menu_msg_id:
        with suppress(Exception):
            await message.bot.edit_message_text(
                chat_id=message.chat.id, 
                message_id=menu_msg_id, 
                text="⏳ <b>Розсилка запущена...</b>", 
                parse_mode="HTML"
            )

    conn = get_connection()
    # Розсилаємо тільки тим, хто НЕ заблокував бота і НЕ забанений
    users = conn.execute("SELECT user_id FROM users WHERE is_blocked_bot = 0 AND is_banned = 0").fetchall()
    conn.close()

    good, bad = 0, 0
    for u in users:
        try:
            await msg_to_send.copy_to(chat_id=u['user_id'])
            good += 1
            await asyncio.sleep(0.05) # Пауза щоб не зловити ліміт
        except:
            bad += 1

    report = (
        f"✅ <b>Розсилку завершено!</b>\n\n"
        f"📨 Успішно: {good}\n"
        f"💀 Помилок/Блокувань: {bad}"
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
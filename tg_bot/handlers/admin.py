import os
import asyncio
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from contextlib import suppress
from aiogram import Router, F, types, Bot
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.exceptions import TelegramBadRequest

# Імпорти з бази даних
from database import (
    get_connection, get_stats_extended, get_stats_general, 
    get_top_routes, get_conversion_rate, get_financial_stats,
    get_peak_hours, get_top_failed_searches, get_top_sources,
    get_user, cancel_trip_full, get_all_active_trips_paginated,
    get_trip_passengers, get_efficiency_stats
)
from config import DB_FILE, ADMIN_IDS

router = Router()

class AdminStates(StatesGroup):
    broadcast = State()
    find_user = State()
    viewing_trips = State() # Стан перегляду поїздок

# ==========================================
# 🏠 ГОЛОВНИЙ ДАШБОРД
# ==========================================

async def render_admin_dashboard(message: types.Message, edit: bool = False):
    """Головна сторінка: стан системи на поточну хвилину."""
    gen_stats = get_stats_general()
    ext_stats = get_stats_extended()
    total_gmv = get_financial_stats()

    text = (
        f"👨‍💻 <b>ПАНЕЛЬ АДМІНІСТРАТОРА v2.1</b>\n"
        f"<i>Стан проекту на зараз</i>\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"👥 <b>Аудиторія:</b>\n"
        f"• Всього юзерів: <b>{ext_stats['total_users']}</b>\n"
        f"• Водіїв: <b>{ext_stats['drivers']}</b> | Пасажирів: <b>{ext_stats['passengers']}</b>\n"
        f"• Нових за сьогодні: <b>+{ext_stats['new_today']}</b>\n"
        f"• Активних (DAU): <b>{ext_stats['dau']}</b>\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"🚗 <b>Поїздки:</b>\n"
        f"• Активних зараз: <b>{gen_stats['active_trips']}</b> 🟢\n"
        f"• Завершених: <b>{gen_stats['finished_trips']}</b>\n"
        f"• Бронювань: <b>{gen_stats['total_bookings']}</b>\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"💰 <b>Обіг (GMV):</b> <code>{total_gmv} грн</code>"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔍 CRM / Юзер", callback_data="admin_find_user_start"),
            InlineKeyboardButton(text="📋 Керування поїздками", callback_data="admin_trips_start")
        ],
        [
            InlineKeyboardButton(text="📈 Маркетинг", callback_data="admin_stats_users"),
            InlineKeyboardButton(text="🛒 Продукт та Гроші", callback_data="admin_stats_product")
        ],
        [InlineKeyboardButton(text="📢 Розсилка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="💾 Скачати БД", callback_data="admin_export_db")],
        [InlineKeyboardButton(text="🔄 Оновити", callback_data="admin_back_home")]
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
# 📋 АКТИВНІ ПОЇЗДКИ (КАРТКИ)
# ==========================================

@router.callback_query(F.data == "admin_trips_start")
async def start_viewing_trips(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS: return
    await state.set_state(AdminStates.viewing_trips)
    await state.update_data(trip_page=0)
    await _render_trip_card(call.message, state)

@router.callback_query(F.data == "admin_trip_next")
async def next_trip_page(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.update_data(trip_page=data.get('trip_page', 0) + 1)
    await _render_trip_card(call.message, state)

@router.callback_query(F.data == "admin_trip_prev")
async def prev_trip_page(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    page = data.get('trip_page', 0)
    if page > 0:
        await state.update_data(trip_page=page - 1)
    await _render_trip_card(call.message, state)

async def _render_trip_card(message: types.Message, state: FSMContext):
    data = await state.get_data()
    page = data.get('trip_page', 0)
    
    # Отримуємо 1 поїздку для поточної сторінки
    trips, total_count = get_all_active_trips_paginated(limit=1, offset=page)
    
    if not trips:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back_home")]])
        if page > 0:
            # Якщо видалили останню і список змістився
            await state.update_data(trip_page=page - 1)
            await _render_trip_card(message, state)
            return
        
        try: await message.edit_text("📭 <b>Активних поїздок немає.</b>", reply_markup=kb, parse_mode="HTML")
        except: pass
        return

    trip = trips[0]
    passengers = get_trip_passengers(trip['id'])
    
    pass_list = ""
    if passengers:
        pass_list = "\n👥 <b>Пасажири:</b>"
        for p in passengers:
            p_name = p['name'] or "Без імені"
            pass_list += f"\n- {p_name} (<code>{p['phone']}</code>)"
    else:
        pass_list = "\n👥 Пасажирів немає."

    uname = f"@{trip['username']}" if trip['username'] else "NoUser"
    desc = f"\n💬 Комент: <i>{trip['description']}</i>" if trip['description'] else ""

    text = (
        f"📋 <b>Поїздка {page + 1} з {total_count}</b>\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"🚗 <b>{trip['origin']} ➝ {trip['destination']}</b>\n"
        f"📅 {trip['date']} | ⏰ {trip['time']}\n"
        f"💰 <b>{trip['price']} грн</b> | 💺 {trip['seats_taken']}/{trip['seats_total']}\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"👤 <b>Водій:</b> {trip['name']}\n"
        f"📱 <code>{trip['phone']}</code> ({uname})\n"
        f"🚙 {trip['model']} {trip['color']} (⭐ {trip['rating_driver']:.1f}){desc}\n"
        f"{pass_list}"
    )

    # Кнопки навігації
    nav_btns = []
    if page > 0: nav_btns.append(InlineKeyboardButton(text="⬅️", callback_data="admin_trip_prev"))
    if page < total_count - 1: nav_btns.append(InlineKeyboardButton(text="➡️", callback_data="admin_trip_next"))

    kb = InlineKeyboardMarkup(inline_keyboard=[
        nav_btns,
        [InlineKeyboardButton(text="❌ ВИДАЛИТИ ЦЮ ПОЇЗДКУ", callback_data=f"admin_trip_del_{trip['id']}")],
        [InlineKeyboardButton(text="🔙 Вихід в меню", callback_data="admin_back_home")]
    ])

    try: await message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except: await message.answer(text, reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data.startswith("admin_trip_del_"))
async def admin_delete_trip_handler(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS: return
    trip_id = call.data.split("_")[3]
    
    # Знаходимо власника для коректного скасування
    conn = get_connection()
    trip_data = conn.execute("SELECT user_id FROM trips WHERE id = ?", (trip_id,)).fetchone()
    conn.close()
    
    if trip_data:
        driver_id = trip_data['user_id']
        trip_info, passengers = cancel_trip_full(trip_id, driver_id)
        
        await call.answer("Поїздку видалено.", show_alert=True)
        
        # Сповіщення
        with suppress(Exception): await call.bot.send_message(driver_id, f"⛔ <b>Вашу поїздку видалено адміністратором.</b>\n{trip_info['origin']} - {trip_info['destination']}", parse_mode="HTML")
        for pid in passengers:
            with suppress(Exception): await call.bot.send_message(pid, f"⚠️ <b>Поїздку скасовано адміністрацією.</b>\n{trip_info['origin']} - {trip_info['destination']}", parse_mode="HTML")
    else:
        await call.answer("Поїздка вже не існує.", show_alert=True)

    # Оновлюємо картку (покаже наступну або попередню)
    await _render_trip_card(call.message, state)


# ==========================================
# 📈 РОЗШИРЕНА СТАТИСТИКА
# ==========================================

@router.callback_query(F.data == "admin_stats_users")
async def show_users_stats(call: types.CallbackQuery):
    if call.from_user.id not in ADMIN_IDS: return
    stats = get_stats_extended()
    top_sources = get_top_sources()
    sources_text = "".join([f"├ 🔗 {src}: <b>{count}</b>\n" for src, count in top_sources]) or "├ (немає даних)\n"
    
    text = (
        f"📈 <b>МАРКЕТИНГ ТА ЛЮДИ</b>\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"<b>📊 Структура бази:</b>\n"
        f"• Водіїв (мають авто): <b>{stats['drivers']}</b>\n"
        f"• Пасажирів: <b>{stats['passengers']}</b>\n\n"
        f"<b>🔗 Джерела трафіку:</b>\n{sources_text}\n"
        f"<b>💀 Відтік (Block):</b> {stats['blocked']} юзерів\n"
        f"<b>❤️ Лояльність (MAU):</b> {stats['mau']} активних за 30 днів"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back_home")]])
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data == "admin_stats_product")
async def show_product_stats(call: types.CallbackQuery):
    if call.from_user.id not in ADMIN_IDS: return
    conversion = get_conversion_rate()
    failed = get_top_failed_searches()
    eff = get_efficiency_stats() # 🔥 Нова статистика
    
    text = (
        f"🛒 <b>ПРОДУКТ ТА ЕКОНОМІКА</b>\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"<b>💰 Гроші:</b>\n"
        f"• Середній чек: <b>{eff['avg_price']} грн</b>\n"
        f"• Заповнюваність авто: <b>{eff['occupancy']}%</b>\n\n"
        f"<b>🎯 Воронка:</b>\n"
        f"• Конверсія в бронь: <b>{conversion}%</b>\n\n"
        f"<b>📉 Втрачений попит (Топ-3):</b>\n"
    )
    for row in failed: text += f"• {row['event_data']} ({row['cnt']})\n"
    if not failed: text += "✅ Дефіциту немає."
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back_home")]])
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

# ==========================================
# 🕵️‍♂️ CRM
# ==========================================
@router.message(Command("reply"))
async def admin_reply_command(message: types.Message, command: CommandObject, bot: Bot):
    if message.from_user.id not in ADMIN_IDS: return
    if not command.args: return await message.answer("⚠️ /reply ID Текст")
    try:
        uid, txt = command.args.split(maxsplit=1)
        await bot.send_message(int(uid), f"👨‍💻 <b>Підтримка:</b>\n\n{txt}", parse_mode="HTML")
        await message.answer(f"✅ Надіслано {uid}")
    except: await message.answer("❌ Помилка")

@router.callback_query(F.data == "admin_find_user_start")
async def find_user_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS: return
    msg = await call.message.edit_text("🕵️‍♂️ Надішліть ID, @username або телефон:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back_home")]]))
    await state.update_data(menu_msg_id=msg.message_id)
    await state.set_state(AdminStates.find_user)

@router.message(AdminStates.find_user)
async def process_find_user(message: types.Message, state: FSMContext, bot: Bot):
    if message.from_user.id not in ADMIN_IDS: return
    
    # 🔥 FIX: Захист від стікерів/фото в адмінці
    if not message.text:
        await message.answer("⚠️ <b>Це не текст.</b>\nНадішліть ID або Username текстом.")
        return

    with suppress(TelegramBadRequest): await message.delete()
    q = message.text.strip()
    
    with get_connection() as conn:
        if q.isdigit(): 
            u = conn.execute("SELECT * FROM users WHERE user_id=?", (int(q),)).fetchone()
            if not u:
                u = conn.execute("SELECT * FROM users WHERE phone LIKE ?", (f"%{q}%",)).fetchone()
        elif q.startswith("@"): 
            u = conn.execute("SELECT * FROM users WHERE username=?", (q,)).fetchone()
        else: 
            if q.startswith("+"):
                 u = conn.execute("SELECT * FROM users WHERE phone LIKE ?", (f"%{q}%",)).fetchone()
            else:
                 u = conn.execute("SELECT * FROM users WHERE username=?", (f"@{q}",)).fetchone()
    data = await state.get_data()
    mid = data.get("menu_msg_id")
    
    if not u:
        if mid: await bot.edit_message_text(f"❌ Не знайдено: {q}", chat_id=message.chat.id, message_id=mid, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙", callback_data="admin_back_home")]]))
        return
    
    txt = f"👤 <b>{u['name']}</b>\n🆔 <code>{u['user_id']}</code>\n📞 {u['phone']}\n⭐ {u['rating_driver']:.1f} / {u['rating_pass']:.1f}\nStatus: {'🚫 BAN' if u['is_banned'] else 'OK'}"
    act = "unban" if u['is_banned'] else "ban"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{'🟢 Unban' if u['is_banned'] else '🔴 BAN'}", callback_data=f"admin_do_{act}_{u['user_id']}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back_home")]
    ])
    if mid: await bot.edit_message_text(txt, chat_id=message.chat.id, message_id=mid, reply_markup=kb, parse_mode="HTML")
    await state.clear()

@router.callback_query(F.data.startswith("admin_do_"))
async def admin_do_action(call: types.CallbackQuery):
    if call.from_user.id not in ADMIN_IDS: return
    act, uid = call.data.split("_")[2], int(call.data.split("_")[3])
    conn = get_connection()
    conn.execute("UPDATE users SET is_banned = ? WHERE user_id = ?", (1 if act=="ban" else 0, uid))
    conn.commit(); conn.close()
    await call.answer(f"Done: {act}")
    await admin_back_home(call, None)

# ==========================================
# 📢 РОЗСИЛКА
# ==========================================
@router.callback_query(F.data == "admin_broadcast")
async def start_broadcast(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS: return
    m = await call.message.edit_text("✍️ Текст/фото для розсилки:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙", callback_data="admin_back_home")]]))
    await state.set_state(AdminStates.broadcast)

@router.message(AdminStates.broadcast)
async def do_broadcast(message: types.Message, state: FSMContext, bot: Bot):
    if message.from_user.id not in ADMIN_IDS: return
    
    await message.answer(f"🚀 Починаю розсилку...")

    async def worker():
        good = 0
        bad = 0
        
        # 🔥 ОПТИМІЗАЦІЯ: Читаємо по 100 юзерів
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT user_id FROM users WHERE is_blocked_bot=0 AND is_banned=0")
        
        while True:
            batch = cursor.fetchmany(100)
            if not batch: break 
            
            blocked_ids_in_batch = []
            
            for row in batch:
                user_id = row[0] 
                try: 
                    await message.copy_to(user_id)
                    good += 1           
                    await asyncio.sleep(0.05) 
                except TelegramForbiddenError:
                    blocked_ids_in_batch.append(user_id)
                    bad += 1
                except Exception: 
                    bad += 1
            
            if blocked_ids_in_batch:
                placeholders = ','.join('?' for _ in blocked_ids_in_batch)
                conn.execute(f"UPDATE users SET is_blocked_bot=1 WHERE user_id IN ({placeholders})", blocked_ids_in_batch)
                conn.commit()

        conn.close()
        await bot.send_message(message.chat.id, f"✅ Розсилка завершена:\n👍 Успішно: {good}\n💀 Заблокували бота: {bad}")

    asyncio.create_task(worker())
    await message.answer("⏳ Процес пішов у фоні. Можете користуватись ботом.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 Додому", callback_data="admin_back_home")]]))
    await state.clear()

@router.callback_query(F.data == "admin_export_db")
async def export_db(call: types.CallbackQuery):
    if call.from_user.id in ADMIN_IDS and os.path.exists(DB_FILE): await call.message.answer_document(FSInputFile(DB_FILE))
    await call.answer()
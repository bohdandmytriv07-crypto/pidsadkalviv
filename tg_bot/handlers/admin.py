import os
import asyncio
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from contextlib import suppress
from aiogram import Router, F, types, Bot
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile

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
    # 🔥 Виконуємо запити в окремому потоці, щоб не блокувати бота
    gen_stats = await asyncio.to_thread(get_stats_general)
    ext_stats = await asyncio.to_thread(get_stats_extended)
    total_gmv = await asyncio.to_thread(get_financial_stats)

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
        except: 
            with suppress(Exception): await message.delete()
            await message.answer(text, reply_markup=kb, parse_mode="HTML")
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
    
    # 🔥 Асинхронний запит до БД
    trips, total_count = await asyncio.to_thread(get_all_active_trips_paginated, limit=1, offset=page)
    
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
    # 🔥 Асинхронний запит до БД
    passengers = await asyncio.to_thread(get_trip_passengers, trip['id'])
    
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

# Допоміжна функція для отримання ID власника
def _get_trip_owner_id(trip_id):
    conn = get_connection()
    row = conn.execute("SELECT user_id FROM trips WHERE id = ?", (trip_id,)).fetchone()
    conn.close()
    return row['user_id'] if row else None

@router.callback_query(F.data.startswith("admin_trip_del_"))
async def admin_delete_trip_handler(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS: return
    trip_id = call.data.split("_")[3]
    
    # Знаходимо власника асинхронно
    driver_id = await asyncio.to_thread(_get_trip_owner_id, trip_id)
    
    if driver_id:
        # Скасовуємо поїздку (це включає SQL транзакції, тому теж в потік)
        trip_info, passengers = await asyncio.to_thread(cancel_trip_full, trip_id, driver_id)
        
        await call.answer("Поїздку видалено.", show_alert=True)
        
        # Сповіщення
        with suppress(Exception): await call.bot.send_message(driver_id, f"⛔ <b>Вашу поїздку видалено адміністратором.</b>\n{trip_info['origin']} - {trip_info['destination']}", parse_mode="HTML")
        for pid in passengers:
            with suppress(Exception): await call.bot.send_message(pid, f"⚠️ <b>Поїздку скасовано адміністрацією.</b>\n{trip_info['origin']} - {trip_info['destination']}", parse_mode="HTML")
    else:
        await call.answer("Поїздка вже не існує.", show_alert=True)

    # Оновлюємо картку
    await _render_trip_card(call.message, state)


# ==========================================
# 📈 РОЗШИРЕНА СТАТИСТИКА
# ==========================================

@router.callback_query(F.data == "admin_stats_users")
async def show_users_stats(call: types.CallbackQuery):
    if call.from_user.id not in ADMIN_IDS: return
    stats = await asyncio.to_thread(get_stats_extended)
    top_sources = await asyncio.to_thread(get_top_sources)
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
    conversion = await asyncio.to_thread(get_conversion_rate)
    failed = await asyncio.to_thread(get_top_failed_searches)
    eff = await asyncio.to_thread(get_efficiency_stats)
    
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

# Допоміжна функція пошуку
def _db_search_user(q):
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
        return dict(u) if u else None

@router.message(AdminStates.find_user)
async def process_find_user(message: types.Message, state: FSMContext, bot: Bot):
    if message.from_user.id not in ADMIN_IDS: return
    
    if not message.text:
        await message.answer("⚠️ <b>Це не текст.</b>")
        return

    with suppress(TelegramBadRequest): await message.delete()
    q = message.text.strip()
    
    # 🔥 Асинхронний пошук
    u = await asyncio.to_thread(_db_search_user, q)

    data = await state.get_data()
    mid = data.get("menu_msg_id")
    
    if not u:
        if mid: 
            with suppress(Exception):
                await bot.edit_message_text(f"❌ Не знайдено: {q}", chat_id=message.chat.id, message_id=mid, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙", callback_data="admin_back_home")]]))
        return
    
    txt = f"👤 <b>{u['name']}</b>\n🆔 <code>{u['user_id']}</code>\n📞 {u['phone']}\n⭐ {u['rating_driver']:.1f} / {u['rating_pass']:.1f}\nStatus: {'🚫 BAN' if u['is_banned'] else 'OK'}"
    act = "unban" if u['is_banned'] else "ban"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{'🟢 Unban' if u['is_banned'] else '🔴 BAN'}", callback_data=f"admin_do_{act}_{u['user_id']}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back_home")]
    ])
    if mid: 
        with suppress(Exception):
            await bot.edit_message_text(txt, chat_id=message.chat.id, message_id=mid, reply_markup=kb, parse_mode="HTML")
    await state.clear()

def _db_update_ban(uid, is_ban):
    conn = get_connection()
    conn.execute("UPDATE users SET is_banned = ? WHERE user_id = ?", (1 if is_ban else 0, uid))
    conn.commit()
    conn.close()

@router.callback_query(F.data.startswith("admin_do_"))
async def admin_do_action(call: types.CallbackQuery):
    if call.from_user.id not in ADMIN_IDS: return
    act, uid = call.data.split("_")[2], int(call.data.split("_")[3])
    
    await asyncio.to_thread(_db_update_ban, uid, act=="ban")
    
    await call.answer(f"Done: {act}")
    await admin_back_home(call, None)

# ==========================================
# 📢 РОЗСИЛКА (OPTIMIZED & SAFE)
# ==========================================
@router.callback_query(F.data == "admin_broadcast")
async def start_broadcast(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS: return
    m = await call.message.edit_text("✍️ Текст/фото для розсилки:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙", callback_data="admin_back_home")]]))
    await state.set_state(AdminStates.broadcast)

# Функції для безпечної роботи з БД у потоках
def _get_all_broadcast_users():
    conn = get_connection()
    # Беремо ВСІХ активних юзерів одразу (список int займає мало пам'яті)
    rows = conn.execute("SELECT user_id FROM users WHERE is_blocked_bot=0 AND is_banned=0").fetchall()
    conn.close()
    return [r[0] for r in rows]

def _mark_users_blocked_batch(user_ids):
    if not user_ids: return
    conn = get_connection()
    placeholders = ','.join('?' for _ in user_ids)
    conn.execute(f"UPDATE users SET is_blocked_bot=1 WHERE user_id IN ({placeholders})", user_ids)
    conn.commit()
    conn.close()

@router.message(AdminStates.broadcast)
async def do_broadcast(message: types.Message, state: FSMContext, bot: Bot):
    if message.from_user.id not in ADMIN_IDS: return
    
    status_msg = await message.answer(f"🚀 <b>Підготовка...</b>\nЗавантажую список користувачів.")
    
    # 1. Швидко отримуємо всі ID (не тримаємо з'єднання відкритим)
    all_users = await asyncio.to_thread(_get_all_broadcast_users)
    total_users = len(all_users)
    
    await status_msg.edit_text(f"🚀 <b>Починаю розсилку!</b>\nЦіль: {total_users} юзерів.")

    async def worker():
        good = 0
        bad = 0
        batch_size = 50
        
        # Розбиваємо на пачки
        for i in range(0, total_users, batch_size):
            batch = all_users[i : i + batch_size]
            blocked_in_this_batch = []
            
            # 2. Обробляємо пачку (Async I/O)
            for user_id in batch:
                try: 
                    await message.copy_to(user_id)
                    good += 1           
                    await asyncio.sleep(0.04) # Невеликий сліп для лімітів Telegram
                except TelegramForbiddenError:
                    blocked_in_this_batch.append(user_id)
                    bad += 1
                except Exception: 
                    bad += 1
            
            # 3. Оновлюємо статус в БД для заблокованих (Sync DB I/O)
            if blocked_in_this_batch:
                await asyncio.to_thread(_mark_users_blocked_batch, blocked_in_this_batch)
                
            # Оновлюємо статус раз на 10 пачок (500 юзерів)
            if i % 500 == 0 and i > 0:
                with suppress(Exception):
                    await status_msg.edit_text(f"📤 <b>Прогрес:</b> {i}/{total_users}\n✅ {good} | ❌ {bad}")

        await bot.send_message(message.chat.id, f"✅ <b>Розсилка завершена!</b>\n👍 Успішно: {good}\n💀 Заблокували: {bad}")

    asyncio.create_task(worker())
    await message.answer("⏳ Процес пішов у фоні. Можете користуватись ботом.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 Додому", callback_data="admin_back_home")]]))
    await state.clear()

@router.callback_query(F.data == "admin_export_db")
async def export_db(call: types.CallbackQuery):
    if call.from_user.id in ADMIN_IDS and os.path.exists(DB_FILE): 
        await call.message.answer_document(FSInputFile(DB_FILE))
    await call.answer()
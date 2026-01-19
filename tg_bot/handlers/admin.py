import os
import sqlite3
from contextlib import suppress
from aiogram import Router, F, types, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.exceptions import TelegramBadRequest

# Ваші імпорти
from database import get_db
from config import DB_FILE 

ADMIN_ID = 1781542141

router = Router()

class AdminStates(StatesGroup):
    broadcast = State()
    ban_user = State()


# ==========================================
# 🛠 ДОПОМІЖНА ФУНКЦІЯ (Щоб не дублювати код)
# ==========================================

async def render_admin_dashboard(message: types.Message, edit: bool = False):
    """
    Малює головне меню адміна. 
    edit=True -> редагує старе повідомлення.
    edit=False -> надсилає нове.
    """
    total_users = 0
    drivers_count = 0
    active_trips = 0
    finished_trips = 0

    try:
        with get_db() as conn:
            cursor = conn.cursor()
            total_users = cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            drivers_count = cursor.execute("SELECT COUNT(*) FROM users WHERE model != '-'").fetchone()[0]
            
            # Перевірка таблиць (безпечно)
            try:
                active_trips = cursor.execute("SELECT COUNT(*) FROM trips WHERE status='active'").fetchone()[0]
                finished_trips = cursor.execute("SELECT COUNT(*) FROM trips WHERE status='finished'").fetchone()[0]
            except: pass
    except Exception: pass

    passengers_count = total_users - drivers_count

    stats_text = (
        f"👮‍♂️ <b>Панель керування</b>\n\n"
        f"👥 Всього користувачів: <b>{total_users}</b>\n"
        f"🚖 Водіїв: <b>{drivers_count}</b> | 🚶 Пасажирів: <b>{passengers_count}</b>\n"
        f"🚗 Активних поїздок: <b>{active_trips}</b>\n"
        f"🏁 Завершених поїздок: <b>{finished_trips}</b>"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Активні поїздки", callback_data="admin_active_trips")],
        [InlineKeyboardButton(text="📢 Розсилка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="🚫 Бан/Розбан", callback_data="admin_ban_menu")],
        [InlineKeyboardButton(text="💾 Backup", callback_data="admin_export_db"),
         InlineKeyboardButton(text="🗑 Очистка", callback_data="admin_clean_old")]
    ])

    if edit:
        try:
            await message.edit_text(stats_text, reply_markup=kb, parse_mode="HTML")
        except TelegramBadRequest:
            # Якщо повідомлення застаріло або текст не змінився
            await message.delete()
            await message.answer(stats_text, reply_markup=kb, parse_mode="HTML")
    else:
        await message.answer(stats_text, reply_markup=kb, parse_mode="HTML")


# ==========================================
# 🏠 ГОЛОВНЕ МЕНЮ
# ==========================================

@router.message(Command("admin"))
async def admin_start_command(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    
    # Видаляємо команду /admin, щоб було чисто
    with suppress(TelegramBadRequest):
        await message.delete()
        
    await state.clear()
    await render_admin_dashboard(message, edit=False)

@router.callback_query(F.data == "admin_back_home")
async def admin_back_home(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    await state.clear()
    await render_admin_dashboard(call.message, edit=True)


# ==========================================
# 📋 ПЕРЕГЛЯД ПОЇЗДОК
# ==========================================

@router.callback_query(F.data == "admin_active_trips")
async def show_active_trips_handler(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    
    with get_db() as conn:
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
# 🚫 БАН / РОЗБАН (З ОЧИЩЕННЯМ)
# ==========================================

@router.callback_query(F.data == "admin_ban_menu")
async def ban_menu_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return

    text = (
        "🚫 <b>Режим блокування</b>\n\n"
        "Надішліть <b>ID користувача</b> (тільки цифри) або перешліть його повідомлення."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Скасувати", callback_data="admin_back_home")]
    ])
    
    # Редагуємо меню на інструкцію
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    
    # Запам'ятовуємо ID цього повідомлення, щоб потім його видалити/оновити
    await state.update_data(menu_msg_id=call.message.message_id)
    await state.set_state(AdminStates.ban_user)


@router.message(AdminStates.ban_user)
async def process_ban_user(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return

    # 1. Видаляємо повідомлення адміна з ID (щоб не смітити)
    with suppress(TelegramBadRequest):
        await message.delete()

    target_id = None
    if message.forward_from:
        target_id = message.forward_from.id
    elif message.text and message.text.strip().isdigit():
        target_id = int(message.text.strip())

    # Отримуємо ID меню, яке треба оновити
    data = await state.get_data()
    menu_msg_id = data.get("menu_msg_id")

    if not target_id:
        # Якщо ввели дурницю - не шлемо нове, а просто лишаємо все як є (або можна відправити тимчасове)
        return

    result_text = ""
    with get_db() as conn:
        cursor = conn.cursor()
        user_data = cursor.execute("SELECT name, is_banned FROM users WHERE user_id = ?", (target_id,)).fetchone()

        if not user_data:
            result_text = f"❌ Користувача <b>{target_id}</b> не знайдено."
        else:
            new_status = 0 if user_data['is_banned'] else 1
            cursor.execute("UPDATE users SET is_banned = ? WHERE user_id = ?", (new_status, target_id))
            conn.commit()
            
            status_str = "ЗАБАНЕНО 🔴" if new_status else "РОЗБАНЕНО 🟢"
            result_text = f"✅ Користувача <b>{user_data['name']}</b> було {status_str}"

            if new_status:
                with suppress(Exception):
                    await message.bot.send_message(target_id, "⛔ <b>Ваш акаунт заблоковано.</b>", parse_mode="HTML")

    # Оновлюємо старе повідомлення меню результатом
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
# 📢 РОЗСИЛКА (З ОЧИЩЕННЯМ)
# ==========================================

@router.callback_query(F.data == "admin_broadcast")
async def start_broadcast_handler(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Скасувати", callback_data="admin_back_home")]
    ])
    await call.message.edit_text("✍️ <b>Напишіть текст для розсилки</b> (або фото):", reply_markup=kb, parse_mode="HTML")
    
    await state.update_data(menu_msg_id=call.message.message_id)
    await state.set_state(AdminStates.broadcast)


@router.message(AdminStates.broadcast)
async def perform_broadcast(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return

    # Отримуємо ID меню
    data = await state.get_data()
    menu_msg_id = data.get("menu_msg_id")

    # Видаляємо повідомлення адміна (текст розсилки) з чату, щоб було чисто
    # (Але ми його вже скопіювали в message, тому можемо розсилати)
    with suppress(TelegramBadRequest):
        await message.delete()

    # Показуємо статус "Відправка..." замість меню
    if menu_msg_id:
        with suppress(Exception):
            await message.bot.edit_message_text(
                chat_id=message.chat.id, 
                message_id=menu_msg_id, 
                text="⏳ <b>Розсилка запущена...</b>", 
                parse_mode="HTML"
            )

    with get_db() as conn:
        users = conn.execute("SELECT user_id FROM users").fetchall()

    good, bad = 0, 0
    for u in users:
        try:
            await message.copy_to(chat_id=u['user_id'])
            good += 1
        except:
            bad += 1

    # Фінальний звіт (Редагуємо повідомлення "Розсилка запущена...")
    report = (
        f"✅ <b>Розсилку завершено!</b>\n\n"
        f"📨 Успішно: {good}\n"
        f"💀 Блокувань: {bad}"
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
# 💾 ТА ІНШЕ
# ==========================================

@router.callback_query(F.data == "admin_export_db")
async def export_database_handler(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    
    if os.path.exists(DB_FILE):
        # Документ відправляємо новим повідомленням (не можна редагувати текст на файл)
        await call.message.answer_document(FSInputFile(DB_FILE), caption="📦 Backup")
    else:
        await call.answer("Файл не знайдено!", show_alert=True)
    await call.answer()

@router.callback_query(F.data == "admin_clean_old")
async def clean_old_trips_handler(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    await call.answer("ℹ️ Очистка працює автоматично у фоні.", show_alert=True)
import os
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile

from database import get_db
from config import DB_FILE  # Імпорт шляху до БД

router = Router()

# 🔴 ВАШ ID (Краще перенести це в config.py, але можна залишити й тут)
ADMIN_ID = 1781542141

class AdminStates(StatesGroup):
    broadcast = State()
    ban_user = State()


# ==========================================
# 🏠 ГОЛОВНЕ МЕНЮ АДМІНА
# ==========================================

@router.message(Command("admin"))
async def admin_start(message: types.Message, state: FSMContext):
    """
    Відображає головну панель адміністратора зі статистикою.
    """
    # Перевірка на адміна
    if message.from_user.id != ADMIN_ID:
        return

    await state.clear()

    # Отримуємо статистику з БД
    total_users = 0
    drivers_count = 0
    active_trips = 0
    finished_trips = 0

    with get_db() as conn:
        cursor = conn.cursor()
        try:
            total_users = cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            # Водіями вважаємо тих, у кого заповнена модель авто (не дорівнює '-')
            drivers_count = cursor.execute("SELECT COUNT(*) FROM users WHERE model != '-'").fetchone()[0]
            active_trips = cursor.execute("SELECT COUNT(*) FROM trips WHERE status='active'").fetchone()[0]
            finished_trips = cursor.execute("SELECT COUNT(*) FROM trips WHERE status='finished'").fetchone()[0]
        except Exception as e:
            await message.answer(f"⚠️ Помилка отримання статистики: {e}")

    passengers_count = total_users - drivers_count

    stats_text = (
        f"👮‍♂️ <b>Панель керування</b>\n\n"
        f"👥 Всього користувачів: <b>{total_users}</b>\n"
        f"🚖 Водіїв: <b>{drivers_count}</b> | 🚶 Пасажирів: <b>{passengers_count}</b>\n"
        f"🚗 Активних поїздок: <b>{active_trips}</b>\n"
        f"🏁 Завершених поїздок: <b>{finished_trips}</b>"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Розсилка всім", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="💾 Скачати базу (Backup)", callback_data="admin_export_db")],
        [InlineKeyboardButton(text="🚫 Забанити / Розбанити", callback_data="admin_ban_menu")],
        [InlineKeyboardButton(text="🗑 Очистити старі поїздки", callback_data="admin_clean_old")]
    ])

    await message.answer(stats_text, reply_markup=kb, parse_mode="HTML")


# ==========================================
# 💾 1. РЕЗЕРВНЕ КОПІЮВАННЯ (BACKUP)
# ==========================================

@router.callback_query(F.data == "admin_export_db")
async def export_database_handler(call: types.CallbackQuery):
    """
    Відправляє файл бази даних адміністратору.
    """
    if call.from_user.id != ADMIN_ID: 
        return
    
    if os.path.exists(DB_FILE):
        await call.message.answer_document(
            FSInputFile(DB_FILE),
            caption="📦 <b>Резервна копія бази даних.</b>",
            parse_mode="HTML"
        )
    else:
        await call.answer("⚠️ Файл бази даних не знайдено!", show_alert=True)
    
    await call.answer()


# ==========================================
# 🚫 2. БАН / РОЗБАН КОРИСТУВАЧІВ
# ==========================================

@router.callback_query(F.data == "admin_ban_menu")
async def ban_menu_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return

    msg_text = (
        "🚫 <b>Керування блокуванням</b>\n\n"
        "Надішліть сюди:\n"
        "1. Або <b>ID користувача</b> (цифрами)\n"
        "2. Або <b>перешліть повідомлення</b> порушника"
    )
    await call.message.answer(msg_text, parse_mode="HTML")
    await state.set_state(AdminStates.ban_user)
    await call.answer()


@router.message(AdminStates.ban_user)
async def process_ban_user(message: types.Message, state: FSMContext):
    """
    Логіка перемикання статусу бану (Toggle Ban).
    """
    if message.from_user.id != ADMIN_ID: return

    target_user_id = None

    # Спроба отримати ID: або з пересланого повідомлення, або з тексту
    if message.forward_from:
        target_user_id = message.forward_from.id
    elif message.text and message.text.strip().isdigit():
        target_user_id = int(message.text.strip())
    else:
        await message.answer("❌ Це не схоже на ID. Спробуйте ще раз або натисніть /admin")
        return

    # Робота з базою
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Перевіряємо, чи існує користувач
        user_data = cursor.execute(
            "SELECT name, is_banned FROM users WHERE user_id = ?", 
            (target_user_id,)
        ).fetchone()

        if not user_data:
            await message.answer("❌ Користувача з таким ID не знайдено в базі.")
            return

        user_name = user_data['name']       # Використовуємо ключі, бо Row factory
        current_ban_status = user_data['is_banned']
        
        # Інвертуємо статус (1 -> 0, 0 -> 1)
        new_ban_status = 0 if current_ban_status else 1
        
        cursor.execute(
            "UPDATE users SET is_banned = ? WHERE user_id = ?", 
            (new_ban_status, target_user_id)
        )
        conn.commit()

    # Повідомлення адміну
    status_text = "🔴 ЗАБАНЕНО" if new_ban_status else "🟢 РОЗБАНЕНО"
    await message.answer(f"Користувача <b>{user_name}</b> (ID: {target_user_id}) було {status_text}!", parse_mode="HTML")
    await state.clear()

    # Спроба повідомити користувача (якщо забанили)
    if new_ban_status:
        try:
            await message.bot.send_message(
                target_user_id, 
                "⛔ <b>Ваш акаунт було заблоковано адміністрацією.</b>", 
                parse_mode="HTML"
            )
        except Exception:
            pass  # Користувач міг заблокувати бота


# ==========================================
# 📢 3. МАСОВА РОЗСИЛКА (BROADCAST)
# ==========================================

@router.callback_query(F.data == "admin_broadcast")
async def start_broadcast_handler(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    
    await call.message.answer("✍️ <b>Напишіть текст оголошення</b> або надішліть фото з підписом:", parse_mode="HTML")
    await state.set_state(AdminStates.broadcast)
    await call.answer()


@router.message(AdminStates.broadcast)
async def perform_broadcast(message: types.Message, state: FSMContext):
    """
    Виконує розсилку повідомлення всім користувачам.
    """
    if message.from_user.id != ADMIN_ID: return

    with get_db() as conn:
        # Отримуємо список
        users_rows = conn.execute("SELECT user_id FROM users").fetchall()

    total_receivers = len(users_rows)
    await message.answer(f"⏳ Починаю розсилку на {total_receivers} людей...")

    success_count = 0
    blocked_count = 0

    for row in users_rows:
        user_id = row['user_id'] # Доступ через ключ Row
        try:
            # Метод copy_to універсальний для тексту, фото, відео тощо
            await message.copy_to(chat_id=user_id)
            success_count += 1
        except Exception:
            # Найчастіше це означає, що користувач заблокував бота
            blocked_count += 1

    report_text = (
        f"✅ <b>Розсилку завершено!</b>\n\n"
        f"📨 Отримали: {success_count}\n"
        f"🚫 Заблокували бота: {blocked_count}"
    )
    
    await message.answer(report_text, parse_mode="HTML")
    await state.clear()


# ==========================================
# 🗑 4. ІНШЕ
# ==========================================

@router.callback_query(F.data == "admin_clean_old")
async def clean_old_trips_handler(call: types.CallbackQuery):
    """
    Заглушка для ручного очищення.
    """
    if call.from_user.id != ADMIN_ID: return
    await call.answer("ℹ️ Система автоматично очищує старі поїздки кожну хвилину.", show_alert=True)
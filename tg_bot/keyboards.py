from datetime import datetime, timedelta
from typing import List, Tuple
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# ==========================================
# 🏠 ГОЛОВНІ МЕНЮ
# ==========================================

def kb_main_role() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚗 Я водій", callback_data="role_driver")],
        [InlineKeyboardButton(text="🚶 Я пасажир", callback_data="role_passenger")],
        [InlineKeyboardButton(text="🆘 Підтримка / Баг", callback_data="support")],
    ])

def kb_menu(role: str) -> InlineKeyboardMarkup:
    if role == "driver":
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Створити поїздку", callback_data="drv_create")],
            [InlineKeyboardButton(text="🗂 Мої поїздки", callback_data="drv_my_trips")],
            [InlineKeyboardButton(text="👤 Мій профіль", callback_data="profile_edit")],
            [InlineKeyboardButton(text="🔙 Змінити роль", callback_data="back_start")],
        ])
    else:
        # role == "passenger"
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Знайти поїздку", callback_data="pass_find")],
            [InlineKeyboardButton(text="🎫 Мої бронювання", callback_data="pass_my_books")],
            [InlineKeyboardButton(text="📜 Історія поїздок", callback_data="pass_history")],
            [InlineKeyboardButton(text="👤 Мій профіль", callback_data="profile_edit")],
            [InlineKeyboardButton(text="🔙 Змінити роль", callback_data="back_start")]
        ])

# ==========================================
# 🛠 ДОПОМІЖНІ
# ==========================================

def kb_back(callback_data: str = "menu_home") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data=callback_data)]])

def kb_dates(prefix: str = "date") -> InlineKeyboardMarkup:
    buttons = []
    now = datetime.now()
    for i in range(4):
        date_obj = now + timedelta(days=i)
        date_str = date_obj.strftime("%d.%m")
        label = "Сьогодні" if i == 0 else ("Завтра" if i == 1 else date_str)
        buttons.append(InlineKeyboardButton(text=label, callback_data=f"{prefix}_{date_str}"))
    
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton(text="🔙 Скасувати", callback_data="menu_home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def kb_car_type():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚗 Легкова", callback_data="body_car")],
        [InlineKeyboardButton(text="🚐 Бус / Мінівен", callback_data="body_bus")]
    ])

# ==========================================
# 💬 ЧАТ
# ==========================================

def kb_chat_actions(partner_username=None):
    """Inline-кнопки під повідомленнями."""
    buttons = [
        [
            InlineKeyboardButton(text="📍 Я на місці", callback_data="tpl_here"),
            InlineKeyboardButton(text="⏱ Запізнююсь 5 хв", callback_data="tpl_late")
        ]
    ]
    if partner_username:
        buttons.append([InlineKeyboardButton(text="✈️ Написати в ПП", url=f"https://t.me/{partner_username}")])
    
    buttons.append([InlineKeyboardButton(text="❌ Завершити діалог", callback_data="chat_leave")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# 🔥 ОСЬ ЦЯ ФУНКЦІЯ, ЯКОЇ НЕ ВИСТАЧАЛО
def kb_reply(user_id):
    """Кнопка 'Відповісти' під повідомленням."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Відповісти", callback_data=f"chat_reply_{user_id}")]
    ])

def kb_chat_bottom():
    """Нижня клавіатура для зручності."""
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="❌ Завершити діалог")],
        [KeyboardButton(text="📍 Надіслати геопозицію", request_location=True), KeyboardButton(text="📞 Надіслати мій номер", request_contact=True)]
    ], resize_keyboard=True)
def kb_plate_type():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇺🇦 Держ. номер (AA1234AA)", callback_data="plate_type_std")],
        [InlineKeyboardButton(text="😎 Іменний / Інший", callback_data="plate_type_custom")]
    ])
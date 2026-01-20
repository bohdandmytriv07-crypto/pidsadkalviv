from datetime import datetime, timedelta
from typing import List, Tuple
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, 
    ReplyKeyboardMarkup, KeyboardButton, 
    ReplyKeyboardRemove
)

# --- КОНСТАНТИ ---
SUPPORT_URL = "https://t.me/senkidesigner"


# ==========================================
# 🏠 ГОЛОВНІ МЕНЮ
# ==========================================

def kb_main_role() -> InlineKeyboardMarkup:
    """
    Клавіатура вибору ролі (Старт).
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚗 Я водій", callback_data="role_driver")],
        [InlineKeyboardButton(text="🚶 Я пасажир", callback_data="role_passenger")],
        [InlineKeyboardButton(text="🆘 Підтримка / Баг", url=SUPPORT_URL)],
    ])


def kb_menu(role: str) -> InlineKeyboardMarkup:
    """
    Генерує головне меню залежно від ролі користувача.
    """
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
# 🛠 ДОПОМІЖНІ КЛАВІАТУРИ
# ==========================================

def kb_back(callback_data: str = "menu_home") -> InlineKeyboardMarkup:
    """
    Проста кнопка "Назад".
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data=callback_data)]
    ])


def kb_simple_list(items: List[Tuple[str, str]], prefix: str) -> InlineKeyboardMarkup:
    """
    Генерує сітку кнопок (по 2 в ряд) зі списку кортежів [(Назва, Значення)].
    """
    # Створюємо список об'єктів кнопок
    buttons = [
        InlineKeyboardButton(text=label, callback_data=f"{prefix}_{value}") 
        for label, value in items
    ]
    
    # Розбиваємо список на ряди по 2 кнопки (chunking)
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    
    # Додаємо кнопку "Скасувати" в кінці
    rows.append([InlineKeyboardButton(text="🔙 Скасувати", callback_data="menu_home")])
    
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_dates(prefix: str = "date") -> InlineKeyboardMarkup:
    """
    Генерує кнопки з датами на найближчі 4 дні.
    """
    buttons = []
    now = datetime.now()
    
    for i in range(4):
        date_obj = now + timedelta(days=i)
        date_str = date_obj.strftime("%d.%m")
        
        # Формуємо красивий підпис (Сьогодні, Завтра або Дата)
        if i == 0:
            label = "Сьогодні"
        elif i == 1:
            label = "Завтра"
        else:
            label = date_str
            
        buttons.append(InlineKeyboardButton(text=label, callback_data=f"{prefix}_{date_str}"))
    
    # Розбиваємо по 2 в ряд
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    
    # Додаємо кнопку "Скасувати"
    rows.append([InlineKeyboardButton(text="🔙 Скасувати", callback_data="menu_home")])
    
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ==========================================
# 💬 ЧАТ (КНОПКИ ЗНИЗУ)
# ==========================================

def kb_chat_actions() -> ReplyKeyboardMarkup:
    """
    Кнопка знизу екрану для завершення чату.
    """
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="❌ Завершити чат")]
        ],
        resize_keyboard=True,
        is_persistent=True # Щоб кнопка не зникала після натискання
    )
def kb_car_type():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚗 Легкова", callback_data="body_car")],
        [InlineKeyboardButton(text="🚐 Бус / Мінівен", callback_data="body_bus")]
    ])
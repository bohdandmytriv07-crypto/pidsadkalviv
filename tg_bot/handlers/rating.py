# 📂 handlers/rating.py

from contextlib import suppress
from aiogram import Router, F, types, Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database import add_review, get_user

router = Router()

def kb_rate_stars(target_id, trip_id, role):
    """Кнопки від 1 до 5 зірок."""
    buttons = []
    for i in range(1, 6):
        # callback: rate_SCORE_TARGET_TRIP_ROLE
        buttons.append(InlineKeyboardButton(text=f"{i} ⭐", callback_data=f"rate_{i}_{target_id}_{trip_id}_{role}"))
    
    return InlineKeyboardMarkup(inline_keyboard=[buttons])

@router.callback_query(F.data.startswith("rate_"))
async def process_rating(call: types.CallbackQuery):
    # Розбираємо дані: rate_5_123456_uuid_driver
    parts = call.data.split("_")
    score = int(parts[1])
    target_id = int(parts[2])
    trip_id = parts[3]
    role_being_rated = parts[4] # Кого оцінили (driver/passenger)
    
    from_id = call.from_user.id
    
    # Записуємо в базу
    success = add_review(trip_id, from_id, target_id, score, role_being_rated)
    
    if success:
        target_user = get_user(target_id)
        name = target_user['name'] if target_user else "Користувача"
        
        with suppress(Exception):
            await call.message.edit_text(
                f"✅ Ви оцінили <b>{name}</b> на <b>{score} ⭐</b>.\nДякуємо!",
                parse_mode="HTML"
            )
            
        # (Опціонально) Можна сповістити того, кого оцінили
        # await call.bot.send_message(target_id, f"🌟 Вам поставили оцінку {score} ⭐ за останню поїздку!")
    else:
        await call.answer("Ви вже оцінили цього користувача.", show_alert=True)
        with suppress(Exception):
            await call.message.delete()

# Функція запуску опитування (викликається з інших хендлерів)
async def ask_for_ratings(bot: Bot, trip_id: str, driver_id: int, passengers: list):
    """
    Розсилає запити на оцінку всім учасникам.
    """
    # 1. Просимо ПАСАЖИРІВ оцінити ВОДІЯ
    driver_info = get_user(driver_id)
    if driver_info:
        for p in passengers:
            text = (
                f"🏁 <b>Поїздка завершена!</b>\n\n"
                f"Як вам водій <b>{driver_info['name']}</b>?\n"
                f"Будь ласка, поставте оцінку:"
            )
            try:
                await bot.send_message(
                    p['user_id'], 
                    text, 
                    reply_markup=kb_rate_stars(driver_id, trip_id, "driver"),
                    parse_mode="HTML"
                )
            except: pass

    # 2. Просимо ВОДІЯ оцінити ПАСАЖИРІВ
    if passengers:
        for p in passengers:
            text = (
                f"🏁 <b>Поїздка завершена!</b>\n\n"
                f"Оцініть пасажира <b>{p['name']}</b>:"
            )
            try:
                await bot.send_message(
                    driver_id, 
                    text, 
                    reply_markup=kb_rate_stars(p['user_id'], trip_id, "passenger"),
                    parse_mode="HTML"
                )
            except: pass
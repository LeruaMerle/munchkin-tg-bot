import os
import asyncio
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, FSInputFile
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database import (
    init_db, get_pet, update_pet, start_action, 
    complete_action, get_finished_actions, get_hungry_pets, mark_notified
)
from guide import GUIDE_TEXT

BOT_TOKEN = ("8966880292:AAEkLtUvC0xRyRBqMH40OMfkzAO5ioo2sys")
APP_URL = ("https://munchkin-tg-bot.onrender.com")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()

def get_launch_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🎮 Играть с Луной (Mini App)", 
                web_app=WebAppInfo(url=APP_URL)
            )
        ],
        [
            InlineKeyboardButton(text="📖 Гайд по манчкинам", callback_data="show_guide")
        ]
    ])

# Проверка окончания минутного таймера и отправка пуша
async def check_finished_actions_job():
    finished = await get_finished_actions()
    for user_id, action in finished:
        msg = ""
        if action == "feed":
            await complete_action(user_id, hunger_delta=30, energy_delta=5, happiness_delta=10)
            msg = "🍲 **Луна покушала!**\nОна сыта, умывает мордочку и довольно мурлычет."
        elif action == "play":
            await complete_action(user_id, hunger_delta=-10, energy_delta=-15, happiness_delta=30)
            msg = "🐭 **Луна закончила играть!**\nОна вдоволь набегалась за мышонком и очень счастлива!"
        elif action == "sleep":
            await complete_action(user_id, hunger_delta=-5, energy_delta=40, happiness_delta=10)
            msg = "💤 **Луна выспалась!**\nОна сладко потянулась на коротких лапках и полна энергии!"

        if msg:
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text=f"{msg}\nЗагляните в игру, чтобы навестить малышку 🐾",
                    reply_markup=get_launch_keyboard(),
                    parse_mode="Markdown"
                )
            except Exception as e:
                print(f"Ошибка пуша завершения действия: {e}")

# Проверка голода (раз в 15 минут)
async def check_hungry_pets_job():
    pets = await get_hungry_pets()
    for user_id, hunger, happiness, notified in pets:
        if (hunger < 30 or happiness < 25) and notified == 0:
            try:
                reason = "проголодалась! Пора покушать 🥣" if hunger < 30 else "соскучилась по вам 🧶"
                await bot.send_message(
                    chat_id=user_id,
                    text=f"🔔 **Напоминание о Луне!**\n\nМалышка {reason}!",
                    reply_markup=get_launch_keyboard(),
                    parse_mode="Markdown"
                )
                await mark_notified(user_id)
            except Exception as e:
                print(f"Ошибка отправки: {e}")

@dp.message(CommandStart())
async def start_handler(message: types.Message):
    photo_path = "static/luna.jpg"
    welcome_caption = (
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        f"Познакомься, это твоя подопечная — **кошечка манчкин по имени Луна**! 🐾\n\n"
        f"Нажми кнопку ниже, чтобы открыть мини-игру, погладить её, покормить, поиграть или уложить спать с живой анимацией."
    )

    if os.path.exists(photo_path):
        photo = FSInputFile(photo_path)
        await message.answer_photo(
            photo=photo,
            caption=welcome_caption,
            reply_markup=get_launch_keyboard(),
            parse_mode="Markdown"
        )
    else:
        await message.answer(
            text=welcome_caption,
            reply_markup=get_launch_keyboard(),
            parse_mode="Markdown"
        )

    await message.answer(GUIDE_TEXT, parse_mode="Markdown")

@dp.callback_query(F.data == "show_guide")
async def show_guide_cb(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.answer(GUIDE_TEXT, parse_mode="Markdown")

# --- FastAPI сервер ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # Проверка завершения минутного действия каждые 5 секунд
    scheduler.add_job(check_finished_actions_job, "interval", seconds=5)
    # Проверка голода каждые 15 минут
    scheduler.add_job(check_hungry_pets_job, "interval", minutes=15)
    scheduler.start()

    bot_task = asyncio.create_task(dp.start_polling(bot))
    yield
    bot_task.cancel()
    scheduler.shutdown()

app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")

class ActionPayload(BaseModel):
    hunger: int = 0
    energy: int = 0
    happiness: int = 0

@app.get("/")
async def index():
    return FileResponse("static/index.html")

@app.get("/api/pet")
async def api_get_pet(user_id: int):
    return await get_pet(user_id)

@app.post("/api/pet/start")
async def api_start_action(user_id: int, action: str):
    # Запускаем таймер ровно на 60 секунд
    return await start_action(user_id, action, duration_sec=60)

@app.post("/api/pet/finish")
async def api_finish_action(user_id: int):
    pet = await get_pet(user_id)
    action = pet.get("current_action", "")
    if action == "feed":
        return await complete_action(user_id, hunger_delta=30, energy_delta=5, happiness_delta=10)
    elif action == "play":
        return await complete_action(user_id, hunger_delta=-10, energy_delta=-15, happiness_delta=30)
    elif action == "sleep":
        return await complete_action(user_id, hunger_delta=-5, energy_delta=40, happiness_delta=10)
    return pet

@app.post("/api/pet/action")
async def api_action(user_id: int, payload: ActionPayload):
    return await update_pet(
        user_id,
        hunger_delta=payload.hunger,
        energy_delta=payload.energy,
        happiness_delta=payload.happiness
    )

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)

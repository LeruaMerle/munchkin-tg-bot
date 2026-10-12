import os
import asyncio
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, FSInputFile
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database import init_db, get_pet, update_pet, get_hungry_pets, mark_notified
from guide import GUIDE_TEXT

# Переменные окружения (на хостинге задаются в настройках, локально берутся значения по умолчанию)
BOT_TOKEN = os.getenv("BOT_TOKEN", "ВАШ_ТОКЕН_БОТА")
# Публичный адрес сайта на хостинге (например, https://munchkin-luna.onrender.com)
APP_URL = os.getenv("APP_URL", "https://your-app-name.onrender.com")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()

# --- Логика Telegram-бота ---

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

async def check_and_send_reminders():
    pets = await get_hungry_pets()
    for user_id, hunger, happiness, notified in pets:
        if (hunger < 30 or happiness < 25) and notified == 0:
            try:
                reason = "голодна! Пора подкрепиться 🥣" if hunger < 30 else "соскучилась по играм 🧶"
                await bot.send_message(
                    chat_id=user_id,
                    text=f"🔔 **Напоминание!**\n\nЛуна {reason}\nОткрой игру и позаботься о малышке!",
                    reply_markup=get_launch_keyboard(),
                    parse_mode="Markdown"
                )
                await mark_notified(user_id)
            except Exception as e:
                print(f"Ошибка отправки: {e}")

@dp.message(CommandStart())
async def start_handler(message: types.Message):
    welcome_text = (
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        f"Перед тобой игра с коротколапой **кошечкой Луной**! 🐾\n"
        f"Нажми кнопку ниже, чтобы открыть приложение, погладить Луну, покормить её или поиграть удочкой.\n\n"
        f"{GUIDE_TEXT}"
    )
    photo_path = "static/luna.jpg"
    if os.path.exists(photo_path):
        photo = FSInputFile(photo_path)
        await message.answer_photo(
            photo=photo,
            caption=welcome_text,
            reply_markup=get_launch_keyboard(),
            parse_mode="Markdown"
        )
    else:
        await message.answer(
            text=welcome_text,
            reply_markup=get_launch_keyboard(),
            parse_mode="Markdown"
        )

@dp.callback_query(F.data == "show_guide")
async def show_guide_cb(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.answer(GUIDE_TEXT, parse_mode="Markdown")

# --- Жизненный цикл FastAPI и запуск бота в фоне ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    scheduler.add_job(check_and_send_reminders, "interval", minutes=15)
    scheduler.start()
    
    # Запускаем поллинг бота параллельно с веб-сервером
    bot_task = asyncio.create_task(dp.start_polling(bot))
    print("Бот и сервер успешно запущены!")
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
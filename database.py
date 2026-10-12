import aiosqlite
import time

DB_NAME = "munchkin_pet.db"

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS pets (
                user_id INTEGER PRIMARY KEY,
                name TEXT DEFAULT 'Луна',
                breed TEXT DEFAULT 'Манчкин',
                hunger INTEGER DEFAULT 80,
                energy INTEGER DEFAULT 80,
                happiness INTEGER DEFAULT 80,
                last_update INTEGER,
                notified INTEGER DEFAULT 0,
                busy_until INTEGER DEFAULT 0,
                current_action TEXT DEFAULT ''
            )
        """)
        # Безопасное добавление колонок, если таблица была создана ранее
        try:
            await db.execute("ALTER TABLE pets ADD COLUMN busy_until INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE pets ADD COLUMN current_action TEXT DEFAULT ''")
        except Exception:
            pass
        await db.commit()

async def get_pet(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT name, hunger, energy, happiness, last_update, notified, busy_until, current_action FROM pets WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            now = int(time.time())

            if not row:
                await db.execute(
                    "INSERT INTO pets (user_id, name, breed, hunger, energy, happiness, last_update, notified, busy_until, current_action) "
                    "VALUES (?, 'Луна', 'Манчкин', 80, 80, 80, ?, 0, 0, '')",
                    (user_id, now)
                )
                await db.commit()
                return {
                    "name": "Луна", "hunger": 80, "energy": 80, "happiness": 80,
                    "busy_until": 0, "current_action": ""
                }

            name, hunger, energy, happiness, last_update, notified, busy_until, current_action = row

            intervals = (now - last_update) // 900
            if intervals > 0:
                hunger = max(0, hunger - intervals * 4)
                energy = max(0, energy - intervals * 2)
                happiness = max(0, happiness - intervals * 3)
                await db.execute(
                    "UPDATE pets SET hunger = ?, energy = ?, happiness = ?, last_update = ? WHERE user_id = ?",
                    (hunger, energy, happiness, now, user_id)
                )
                await db.commit()

            return {
                "name": name, "hunger": hunger, "energy": energy, "happiness": happiness,
                "busy_until": busy_until, "current_action": current_action
            }

async def update_pet(user_id: int, hunger_delta: int = 0, energy_delta: int = 0, happiness_delta: int = 0):
    pet = await get_pet(user_id)
    new_hunger = min(100, max(0, pet["hunger"] + hunger_delta))
    new_energy = min(100, max(0, pet["energy"] + energy_delta))
    new_happiness = min(100, max(0, pet["happiness"] + happiness_delta))
    now = int(time.time())

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE pets SET hunger = ?, energy = ?, happiness = ?, last_update = ? WHERE user_id = ?",
            (new_hunger, new_energy, new_happiness, now, user_id)
        )
        await db.commit()

    return {"name": pet["name"], "hunger": new_hunger, "energy": new_energy, "happiness": new_happiness}

async def start_action(user_id: int, action: str, duration_sec: int = 60):
    now = int(time.time())
    busy_until = now + duration_sec
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE pets SET busy_until = ?, current_action = ? WHERE user_id = ?",
            (busy_until, action, user_id)
        )
        await db.commit()
    return await get_pet(user_id)

async def complete_action(user_id: int, hunger_delta: int, energy_delta: int, happiness_delta: int):
    pet = await get_pet(user_id)
    new_hunger = min(100, max(0, pet["hunger"] + hunger_delta))
    new_energy = min(100, max(0, pet["energy"] + energy_delta))
    new_happiness = min(100, max(0, pet["happiness"] + happiness_delta))
    now = int(time.time())

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE pets SET hunger = ?, energy = ?, happiness = ?, last_update = ?, busy_until = 0, current_action = '', notified = 0 WHERE user_id = ?",
            (new_hunger, new_energy, new_happiness, now, user_id)
        )
        await db.commit()
    return {"name": pet["name"], "hunger": new_hunger, "energy": new_energy, "happiness": new_happiness}

async def get_finished_actions():
    now = int(time.time())
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT user_id, current_action FROM pets WHERE busy_until > 0 AND busy_until <= ?", 
            (now,)
        ) as cursor:
            return await cursor.fetchall()

async def get_hungry_pets():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id, hunger, happiness, notified FROM pets WHERE busy_until = 0") as cursor:
            return await cursor.fetchall()

async def mark_notified(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE pets SET notified = 1 WHERE user_id = ?", (user_id,))
        await db.commit()

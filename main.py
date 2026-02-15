"""
Запуск обоих ботов (User Bot + Admin Bot) одновременно через Polling.
Единая БД. Конфиг только из .env (все переменные в одном файле).
"""

import asyncio
import os
import logging

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery
from aiogram import BaseMiddleware

from database import Database
from handlers_user import register_user_handlers
from handlers_admin import register_admin_handlers
from aiogram import Router


class BlacklistMiddleware(BaseMiddleware):
    """Не обрабатывать сообщения от забаненных пользователей."""
    def __init__(self, db: Database):
        self.db = db

    async def __call__(self, handler, event, data):
        if not getattr(event, "from_user", None):
            return await handler(event, data)
        user_id = event.from_user.id
        if await self.db.is_banned(user_id):
            if isinstance(event, Message):
                await event.answer("⛔ Вы заблокированы.")
            elif isinstance(event, CallbackQuery):
                await event.answer("Вы заблокированы.", show_alert=True)
            return
        return await handler(event, data)

# Один файл конфигурации — .env (скопируйте из .env.example и заполните)
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

USER_BOT_TOKEN = os.getenv("USER_BOT_TOKEN")
ADMIN_BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN")
# ADMIN_CHAT_ID — один ID или несколько через запятую (берём первый для уведомлений)
_admin_chat_str = (os.getenv("ADMIN_CHAT_ID") or "0").strip()
_admin_chat_parts = [x.strip() for x in _admin_chat_str.split(",") if x.strip()]
try:
    ADMIN_CHAT_ID = int(_admin_chat_parts[0]) if _admin_chat_parts else 0
except ValueError:
    ADMIN_CHAT_ID = 0
DATABASE_PATH = os.getenv("DATABASE_PATH", "augsburg_liquid.db")
CSV_URL = os.getenv("CSV_URL") or os.getenv("GOOGLE_SHEETS_CSV_URL", "")

# Список ID админов: из ADMIN_IDS или из ADMIN_CHAT_ID (несколько через запятую)
_admin_ids_str = os.getenv("ADMIN_IDS", _admin_chat_str)
ADMIN_IDS = [int(x.strip()) for x in _admin_ids_str.split(",") if x.strip().isdigit()]
if not ADMIN_IDS and ADMIN_CHAT_ID:
    ADMIN_IDS = [ADMIN_CHAT_ID]


async def main():
    if not USER_BOT_TOKEN or not ADMIN_BOT_TOKEN:
        raise ValueError("Задайте USER_BOT_TOKEN и ADMIN_BOT_TOKEN в .env")
    if not CSV_URL:
        logger.warning("CSV_URL не задан — синхронизация из Google Sheets недоступна.")

    db = Database(DATABASE_PATH)
    await db.init_db()

    user_bot = Bot(
        token=USER_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    admin_bot = Bot(
        token=ADMIN_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    user_storage = MemoryStorage()
    user_dp = Dispatcher(storage=user_storage)
    user_dp.message.middleware(BlacklistMiddleware(db))
    user_dp.callback_query.middleware(BlacklistMiddleware(db))
    router_user = Router()
    register_user_handlers(
        router_user,
        db,
        user_bot,
        admin_bot=admin_bot,
        admin_chat_id=ADMIN_CHAT_ID,
    )
    user_dp.include_router(router_user)

    admin_storage = MemoryStorage()
    admin_dp = Dispatcher(storage=admin_storage)
    router_admin = Router()
    register_admin_handlers(
        router_admin,
        db,
        admin_bot,
        csv_url=CSV_URL,
        admin_chat_id=ADMIN_CHAT_ID,
        admin_ids=ADMIN_IDS,
    )
    admin_dp.include_router(router_admin)

    logger.info("User Bot and Admin Bot starting (polling)...")
    await asyncio.gather(
        user_dp.start_polling(user_bot),
        admin_dp.start_polling(admin_bot),
    )


if __name__ == "__main__":
    asyncio.run(main())

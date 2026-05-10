import asyncio
import os
import re
from typing import Optional

from aiogram import Bot, Dispatcher, Router

from download_service import DownloadService
from storage import Storage


def parse_admins(value: Optional[str]) -> list[int]:
    if not value:
        return []
    return [int(item) for item in re.split(r"[,\s]+", value.strip()) if item]


async def main():
    bot_token = os.environ.get("BOT_TOKEN", "")
    admin_user_ids = os.environ.get("ADMIN_USERIDS", "")
    db_path = os.environ.get("DB_PATH", "data/bot.db")

    if not bot_token:
        raise SystemExit("BOT_TOKEN is required")

    admins = parse_admins(admin_user_ids)
    storage = Storage(db_path)
    bot = Bot(token=bot_token)
    dp = Dispatcher()
    router = Router()
    service = DownloadService(bot, storage)

    from handlers import register_message_handlers

    register_message_handlers(router, service, storage, admins)

    dp.include_router(router)

    asyncio.create_task(service.start())
    
    print("Bot is running...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

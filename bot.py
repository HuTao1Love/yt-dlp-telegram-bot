import asyncio
import os
import re
from typing import Optional

from aiogram import Bot, Dispatcher, Router
from aiogram.types import FSInputFile

from download_service import DownloadService
from storage import Storage

from handlers import register_message_handlers
from admin_mirror import install_admin_mirroring
from middleware import ProfileSyncMiddleware


def parse_admins(value: Optional[str]) -> list[int]:
    if not value:
        return []
    return [int(item) for item in re.split(r"[,\s]+", value.strip()) if item]


def load_dotenv(path: str = ".env", override: bool = False) -> None:
    try:
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip()
                if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                if override or key not in os.environ:
                    os.environ[key] = val
    except Exception:
        pass


async def main():
    load_dotenv()
    bot_token = os.environ.get("BOT_TOKEN", "")
    admin_user_ids = os.environ.get("ADMIN_USERIDS", "")
    db_path = os.environ.get("DB_PATH", "data/bot.db")

    if not bot_token:
        raise SystemExit("BOT_TOKEN is required")

    admins = parse_admins(admin_user_ids)
    storage = Storage(db_path)
    bot = Bot(token=bot_token)
    install_admin_mirroring(bot, admins, storage)
    dp = Dispatcher()
    dp.update.outer_middleware(ProfileSyncMiddleware(storage))
    router = Router()
    service = DownloadService(bot, storage)

    register_message_handlers(router, service, storage, admins)

    dp.include_router(router)

    asyncio.create_task(service.start())
    
    print("Bot is running...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

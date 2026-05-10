from collections.abc import Awaitable, Callable
from typing import Any, Dict

from aiogram import BaseMiddleware, F
from aiogram.types import TelegramObject, Update

from storage import Storage


class ProfileSyncMiddleware(BaseMiddleware):
    def __init__(self, storage: Storage):
        self.storage = storage

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if isinstance(event, Update):
            incoming_user = None

            if event.message and event.message.from_user:
                incoming_user = event.message.from_user
            elif event.edited_message and event.edited_message.from_user:
                incoming_user = event.edited_message.from_user
            elif event.callback_query and event.callback_query.from_user:
                incoming_user = event.callback_query.from_user

            if incoming_user:
                self.storage.upsert_user_profile(
                    incoming_user.id,
                    incoming_user.username,
                    incoming_user.first_name,
                    incoming_user.last_name,
                )

        return await handler(event, data)
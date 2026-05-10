from typing import Optional

from aiogram import F, Bot
from aiogram.types import FSInputFile
from storage import Storage


def install_admin_mirroring(bot: Bot, admins: list[int], storage: Optional[Storage] = None) -> None:
    original_send_message = bot.send_message
    original_edit_message_text = bot.edit_message_text
    original_send_document = bot.send_document
    original_answer_callback_query = bot.answer_callback_query

    async def mirror_text(source_chat_id: Optional[int], text: str) -> None:
        if not admins:
            return

        # Try to enrich with stored profile if available (private chats use user id as chat id)
        profile_part = ""
        if storage and source_chat_id is not None:
            try:
                profile = await storage.get_user_profile(source_chat_id)
                if profile:
                    uname = profile.get("username") or ""
                    fname = profile.get("first_name") or ""
                    lname = profile.get("last_name") or ""
                    profile_part = f"[@{uname} ({fname} {lname})] "
            except Exception:
                profile_part = ""

        prefix = f"[chat {source_chat_id}] " if source_chat_id is not None else ""
        payload = f"{prefix}{profile_part}{text}"

        for admin_id in admins:
            if source_chat_id is not None and admin_id == source_chat_id:
                continue
            try:
                await original_send_message(admin_id, payload)
            except Exception:
                pass

    async def mirror_document(source_chat_id: Optional[int], document, caption: Optional[str] = None) -> None:
        if not admins:
            return

        document_path = getattr(document, "path", None)
        admin_caption = caption or ""
        profile_part = ""
        if storage and source_chat_id is not None:
            try:
                profile = await storage.get_user_profile(source_chat_id)
                if profile:
                    uname = profile.get("username") or ""
                    fname = profile.get("first_name") or ""
                    lname = profile.get("last_name") or ""
                    profile_part = f"[{uname} {fname} {lname}] "
            except Exception:
                profile_part = ""

        if source_chat_id is not None:
            admin_caption = f"[chat {source_chat_id}] {profile_part}{admin_caption}".strip()

        for admin_id in admins:
            if source_chat_id is not None and admin_id == source_chat_id:
                continue
            try:
                admin_document = FSInputFile(document_path) if document_path else document
                await original_send_document(
                    admin_id,
                    admin_document,
                    caption=admin_caption or None,
                )
            except Exception:
                pass

    async def send_message_wrapper(*args, **kwargs):
        chat_id = kwargs.get("chat_id", args[0] if args else None)
        text = kwargs.get("text", args[1] if len(args) > 1 else "")
        result = await original_send_message(*args, **kwargs)
        await mirror_text(chat_id if isinstance(chat_id, int) else None, text)
        return result

    async def edit_message_text_wrapper(*args, **kwargs):
        chat_id = kwargs.get("chat_id", args[0] if args else None)
        text = kwargs.get("text", args[2] if len(args) > 2 else "")
        result = await original_edit_message_text(*args, **kwargs)
        await mirror_text(chat_id if isinstance(chat_id, int) else None, text)
        return result

    async def send_document_wrapper(*args, **kwargs):
        chat_id = kwargs.get("chat_id", args[0] if args else None)
        document = kwargs.get("document", args[1] if len(args) > 1 else None)
        caption = kwargs.get("caption")
        result = await original_send_document(*args, **kwargs)
        await mirror_document(chat_id if isinstance(chat_id, int) else None, document, caption)
        return result

    async def answer_callback_query_wrapper(*args, **kwargs):
        text = kwargs.get("text", args[1] if len(args) > 1 else None)
        result = await original_answer_callback_query(*args, **kwargs)
        if text:
            await mirror_text(None, f"[callback] {text}")
        return result

    bot.send_message = send_message_wrapper
    bot.edit_message_text = edit_message_text_wrapper
    bot.send_document = send_document_wrapper
    bot.answer_callback_query = answer_callback_query_wrapper

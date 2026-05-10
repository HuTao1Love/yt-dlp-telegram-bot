from typing import Optional, Union
import uuid

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from download_service import DownloadEntry, DownloadService
from storage import Storage


_url_cache: dict[str, str] = {}


def normalize_group_id(value: int) -> int:
    return -abs(value)


def is_admin(user_id: Optional[int], admins: list[int]) -> bool:
    return user_id is not None and user_id in admins


def is_allowed(event: Union[Message, CallbackQuery], storage: Storage, admins: list[int]) -> bool:
    if isinstance(event, Message):
        user_id = event.from_user.id if event.from_user else None
        chat_id = event.chat.id
        chat_type = event.chat.type
    elif isinstance(event, CallbackQuery):
        user_id = event.from_user.id
        chat_id = event.message.chat.id
        chat_type = event.message.chat.type
    else:
        return False
    
    if is_admin(user_id, admins):
        return True

    if chat_type in {"group", "supergroup"}:
        return chat_id in storage.list_groups()

    return user_id in storage.list_users()


def register_message_handlers(
    router: Router,
    service: DownloadService,
    storage: Storage,
    admins: list[int],
) -> None:
    @router.message(Command("start"))
    async def start_handler(message: Message):
        await message.answer(
            "👋 Welcome!\n\n"
            "📹 Send a URL to download or use `/dlp <url>`\n"
            "💬 Just paste any link and I'll ask you to choose quality\n\n"
            "📋 Commands:\n"
            "`/id` - Your user ID\n"
            "`/dlp <url>` - Download with format selection\n"
            "`/dlpcancel` - Cancel current download",
            parse_mode="Markdown"
        )

    @router.message(Command("id"))
    async def id_handler(message: Message):
        user_id = message.from_user.id if message.from_user else None
        await message.answer(f"user id: `{user_id}`\nchat id: `{message.chat.id}`", parse_mode="MarkdownV2")

    @router.message(Command("dlp"))
    async def dlp_handler(message: Message):
        if not is_allowed(message, storage, admins):
            return
        parts = message.text.split(maxsplit=1) if message.text else []
        if len(parts) < 2 or not parts[1].strip():
            await message.answer("📹 Usage: `/dlp <url>`", parse_mode="Markdown")
            return
        url = parts[1].strip()
        
        # Show loading message
        status_msg = await message.answer("⏳ Fetching video formats...")
        
        # Get available formats
        formats = await service.get_video_formats(url)
        if not formats:
            await status_msg.edit_text("❌ Could not fetch formats or no video formats available")
            return
        
        # Store URL in cache
        url_id = str(uuid.uuid4())[:8]
        _url_cache[url_id] = url
        
        # Create buttons for each quality
        buttons = []
        for fmt in formats:
            height = fmt["height"]
            fps = fmt.get("fps", 30)
            format_id = fmt["format_id"]
            button_text = f"📹 {height}p@{fps}fps"
            button_data = f"fmt_video:{url_id}:{format_id}"
            buttons.append([InlineKeyboardButton(text=button_text, callback_data=button_data)])
        
        # Add audio option
        buttons.append([InlineKeyboardButton(text="🎵 Audio (MP3)", callback_data=f"fmt_audio:{url_id}:mp3")])
        
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        await status_msg.edit_text("📥 Choose quality:", reply_markup=kb)

    @router.callback_query(F.data.startswith("fmt_"))
    async def format_callback(callback: CallbackQuery):
        if not is_allowed(callback, storage, admins):
            await callback.answer("❌ Access denied", show_alert=True)
            return
        
        data_parts = callback.data.split(":", 2)
        fmt = data_parts[0].replace("fmt_", "")
        url_id = data_parts[1] if len(data_parts) > 1 else ""
        format_id = data_parts[2] if len(data_parts) > 2 else None
        
        url = _url_cache.pop(url_id, None)
        if not url:
            await callback.answer("❌ URL expired or invalid", show_alert=True)
            return
        
        entry = DownloadEntry(
            chat_id=callback.message.chat.id,
            user_id=callback.from_user.id,
            url=url,
            fmt=fmt,
            format_id=format_id
        )
        await service.enqueue(entry)
        
        if fmt == "audio":
            status_text = "✅ Audio added to queue"
        elif format_id:
            status_text = f"✅ Video added to queue"
        else:
            status_text = "✅ Added to queue"
        
        await callback.message.edit_text(status_text)
        await callback.answer()

    @router.message(Command("dlpcancel"))
    async def cancel_handler(message: Message):
        if not is_allowed(message, storage, admins):
            return
        if await service.cancel_current(message.chat.id):
            await message.answer("❌ Download cancelled")
        else:
            await message.answer("ℹ️ No active download")

    @router.message(Command("adduser"))
    async def add_user_handler(message: Message):
        if not is_admin(message.from_user.id if message.from_user else None, admins):
            return
        parts = message.text.split(maxsplit=1) if message.text else []
        if len(parts) < 2:
            await message.answer("👤 Usage: `/adduser {id}`", parse_mode="Markdown")
            return
        try:
            user_id = int(parts[1].split()[0])
        except ValueError:
            await message.answer("👤 Usage: `/adduser {id}`", parse_mode="Markdown")
            return
        added = storage.add_user(user_id)
        await message.answer(f"✅ User `{user_id}` added" if added else f"ℹ️ User `{user_id}` already in list", parse_mode="Markdown")

    @router.message(Command("removeuser"))
    async def remove_user_handler(message: Message):
        if not is_admin(message.from_user.id if message.from_user else None, admins):
            return
        parts = message.text.split(maxsplit=1) if message.text else []
        if len(parts) < 2:
            await message.answer("👤 Usage: `/removeuser {id}`", parse_mode="Markdown")
            return
        try:
            user_id = int(parts[1].split()[0])
        except ValueError:
            await message.answer("👤 Usage: `/removeuser {id}`", parse_mode="Markdown")
            return
        removed = storage.remove_user(user_id)
        await message.answer(f"✅ User `{user_id}` removed" if removed else f"❌ User `{user_id}` not found", parse_mode="Markdown")

    @router.message(Command("addgroup"))
    async def add_group_handler(message: Message):
        if not is_admin(message.from_user.id if message.from_user else None, admins):
            return
        parts = message.text.split(maxsplit=1) if message.text else []
        if len(parts) < 2:
            await message.answer("👥 Usage: `/addgroup {id}`", parse_mode="Markdown")
            return
        try:
            group_id = normalize_group_id(int(parts[1].split()[0]))
        except ValueError:
            await message.answer("👥 Usage: `/addgroup {id}`", parse_mode="Markdown")
            return
        added = storage.add_group(group_id)
        await message.answer(f"✅ Group `{group_id}` added" if added else f"ℹ️ Group `{group_id}` already in list", parse_mode="Markdown")

    @router.message(Command("removegroup"))
    async def remove_group_handler(message: Message):
        if not is_admin(message.from_user.id if message.from_user else None, admins):
            return
        parts = message.text.split(maxsplit=1) if message.text else []
        if len(parts) < 2:
            await message.answer("👥 Usage: `/removegroup {id}`", parse_mode="Markdown")
            return
        try:
            group_id = normalize_group_id(int(parts[1].split()[0]))
        except ValueError:
            await message.answer("👥 Usage: `/removegroup {id}`", parse_mode="Markdown")
            return
        removed = storage.remove_group(group_id)
        await message.answer(f"✅ Group `{group_id}` removed" if removed else f"❌ Group `{group_id}` not found", parse_mode="Markdown")

    @router.message(F.text)
    async def text_url_handler(message: Message):
        if not is_allowed(message, storage, admins):
            return
        text = message.text.strip() if message.text else ""
        if not text or text.startswith(("/", "!")):
            return
        
        # Show loading message
        status_msg = await message.answer("⏳ Fetching video formats...")
        
        # Get available formats
        formats = await service.get_video_formats(text)
        if not formats:
            await status_msg.edit_text("❌ Could not fetch formats or no video formats available")
            return
        
        # Store URL in cache
        url_id = str(uuid.uuid4())[:8]
        _url_cache[url_id] = text
        
        # Create buttons for each quality
        buttons = []
        for fmt in formats:
            height = fmt["height"]
            fps = fmt.get("fps", 30)
            format_id = fmt["format_id"]
            button_text = f"📹 {height}p@{fps}fps"
            button_data = f"fmt_video:{url_id}:{format_id}"
            buttons.append([InlineKeyboardButton(text=button_text, callback_data=button_data)])
        
        # Add audio option
        buttons.append([InlineKeyboardButton(text="🎵 Audio (MP3)", callback_data=f"fmt_audio:{url_id}:mp3")])
        
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        await status_msg.edit_text("📥 Choose quality:", reply_markup=kb)
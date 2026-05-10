import asyncio
import logging
import os
import re
import shutil
import tempfile
import json
import uuid
from asyncio.subprocess import DEVNULL, PIPE
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from aiogram import Bot
from aiogram.types import FSInputFile, Message

from storage import Storage


YT_DLP = os.environ.get("YTDLP_PATH", "yt-dlp")
logger = logging.getLogger(__name__)


@dataclass
class DownloadEntry:
    chat_id: int
    user_id: Optional[int]
    url: str
    fmt: str
    format_id: Optional[str] = None
    proc: Optional[asyncio.subprocess.Process] = None
    workdir: Optional[str] = None


class DownloadService:
    def __init__(self, bot: Bot, storage: Storage):
        self.bot = bot
        self.storage = storage
        self.queue: asyncio.Queue[DownloadEntry] = asyncio.Queue()
        self.current: Optional[DownloadEntry] = None

    async def start(self):
        while True:
            entry = await self.queue.get()
            self.current = entry
            logger.info(
                "Started queue item: chat_id=%s user_id=%s fmt=%s format_id=%s url=%s",
                entry.chat_id,
                entry.user_id,
                entry.fmt,
                entry.format_id,
                entry.url,
            )
            try:
                await self._process(entry)
            except Exception as exc:
                logger.exception(
                    "Download failed: chat_id=%s user_id=%s fmt=%s format_id=%s url=%s",
                    entry.chat_id,
                    entry.user_id,
                    entry.fmt,
                    entry.format_id,
                    entry.url,
                )
                await self._safe_reply(entry.chat_id, f"❌ Download failed: {exc}")
            finally:
                self._cleanup(entry)
                self.current = None
                self.queue.task_done()

    async def enqueue(self, entry: DownloadEntry) -> int:
        queue_position = self.queue.qsize() + 1
        if self.current is not None:
            queue_position += 1
        await self.queue.put(entry)
        logger.info(
            "Enqueued download: chat_id=%s user_id=%s fmt=%s format_id=%s position=%s url=%s",
            entry.chat_id,
            entry.user_id,
            entry.fmt,
            entry.format_id,
            queue_position,
            entry.url,
        )
        return queue_position

    async def cancel_current(self, chat_id: int) -> bool:
        if not self.current or self.current.chat_id != chat_id:
            return False
        if self.current.proc and self.current.proc.returncode is None:
            self.current.proc.kill()
            logger.info("Cancelled current download for chat_id=%s", chat_id)
            return True
        return False

    async def get_video_formats(self, url: str) -> list[dict]:
        """Fetch available video formats from yt-dlp."""
        logger.info("Fetching formats for url=%s", url)
        try:
            proc = await asyncio.create_subprocess_exec(
                YT_DLP, "-j", "--no-warnings", url,
                stdout=PIPE, stderr=PIPE
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0:
                data = json.loads(stdout.decode())
                formats = data.get("formats", [])
                # Filter video formats with height info
                video_formats = []
                seen_heights = set()
                for fmt in formats:
                    height = fmt.get("height")
                    if height and height not in seen_heights and fmt.get("vcodec") != "none":
                        seen_heights.add(height)
                        video_formats.append({
                            "format_id": fmt.get("format_id"),
                            "height": height,
                            "ext": fmt.get("ext"),
                            "fps": fmt.get("fps", 30)
                        })
                # Sort by height descending
                video_formats.sort(key=lambda x: x["height"], reverse=True)
                logger.info("Fetched %s video formats for url=%s", len(video_formats[:10]), url)
                return video_formats[:10]  # Return top 10 formats
        except Exception:
            logger.exception("Failed to fetch formats for url=%s", url)
        return []

    async def _process(self, entry: DownloadEntry):
        entry.workdir = tempfile.mkdtemp(prefix="ytdlp_")
        generated_stem = self._build_generated_stem(entry)
        output_template = os.path.join(entry.workdir, f"{generated_stem}.%(ext)s")
        args = [YT_DLP, "--no-playlist", "--newline", "-o", output_template]
        if entry.fmt in ("mp3", "audio"):
            args += ["-x", "--audio-format", "mp3"]
        elif entry.fmt == "video" and entry.format_id:
            args += ["-f", entry.format_id]
        args.append(entry.url)

        status_message = await self._safe_reply(entry.chat_id, "⏳ Download started: 0%")
        status_message_id = status_message.message_id if status_message else None
        logger.info(
            "Running yt-dlp: chat_id=%s fmt=%s format_id=%s output_stem=%s",
            entry.chat_id,
            entry.fmt,
            entry.format_id,
            generated_stem,
        )

        proc = await asyncio.create_subprocess_exec(*args, stdout=DEVNULL, stderr=PIPE)
        entry.proc = proc
        stderr_text = await self._wait_with_progress(entry, proc, status_message_id)
        entry.proc = None

        if proc.returncode != 0:
            raise RuntimeError(stderr_text or "yt-dlp failed")

        file_path = self._find_downloaded_file(entry.workdir)
        if not file_path:
            raise RuntimeError("no file downloaded")

        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        file_name = os.path.basename(file_path)
        info_caption = (
            f"📄 {file_name}\n"
            f"🧾 Type: {'Audio' if entry.fmt in ('mp3', 'audio') else 'Video'}\n"
            f"📦 Size: {file_size_mb:.2f} MB"
        )

        if status_message_id:
            await self._safe_edit(
                entry.chat_id,
                status_message_id,
                "✅ Download finished. Uploading file...",
            )
        else:
            await self._safe_reply(entry.chat_id, "✅ Download finished. Uploading file...")
        logger.info(
            "Upload started: chat_id=%s file=%s size_mb=%.2f",
            entry.chat_id,
            file_name,
            file_size_mb,
        )
        await self.bot.send_document(entry.chat_id, FSInputFile(file_path), caption=info_caption)
        logger.info(
            "Upload completed: chat_id=%s file=%s size_mb=%.2f",
            entry.chat_id,
            file_name,
            file_size_mb,
        )

    def _find_downloaded_file(self, workdir: Optional[str]) -> Optional[str]:
        if not workdir or not os.path.isdir(workdir):
            return None
        candidates = []
        for root, _, files in os.walk(workdir):
            for filename in files:
                candidates.append(os.path.join(root, filename))
        if not candidates:
            return None
        candidates.sort(key=os.path.getmtime)
        return candidates[-1]

    def _cleanup(self, entry: DownloadEntry):
        if entry.workdir and os.path.isdir(entry.workdir):
            logger.info("Cleaning temporary directory: %s", entry.workdir)
            shutil.rmtree(entry.workdir, ignore_errors=True)

    async def _wait_with_progress(
        self,
        entry: DownloadEntry,
        proc: asyncio.subprocess.Process,
        status_message_id: Optional[int],
    ) -> str:
        last_reported = -5.0
        stderr_lines: list[str] = []

        while True:
            raw = await proc.stderr.readline()
            if not raw:
                break

            line = raw.decode(errors="ignore").strip()
            if not line:
                continue
            stderr_lines.append(line)

            progress = self._extract_progress_percent(line)
            if progress is None or status_message_id is None:
                continue

            # Edit message only when progress changes noticeably.
            if progress == 100.0 or progress - last_reported >= 25.0:
                last_reported = progress
                await self._safe_edit(
                    entry.chat_id,
                    status_message_id,
                    f"⏳ Downloading: {progress:.1f}%",
                )

        await proc.wait()
        return "\n".join(stderr_lines[-20:]).strip()

    def _extract_progress_percent(self, line: str) -> Optional[float]:
        match = re.search(r"(\d+(?:\.\d+)?)%", line)
        if not match:
            return None
        try:
            return min(100.0, max(0.0, float(match.group(1))))
        except ValueError:
            return None

    def _build_generated_stem(self, entry: DownloadEntry) -> str:
        prefix = "audio" if entry.fmt in ("mp3", "audio") else "video"
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        token = uuid.uuid4().hex[:8]
        return f"{prefix}_{timestamp}_{token}"

    async def _safe_reply(self, chat_id: int, text: str) -> Optional[Message]:
        try:
            return await self.bot.send_message(chat_id, text)
        except Exception:
            return None

    async def _safe_edit(self, chat_id: int, message_id: int, text: str) -> None:
        try:
            await self.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text)
        except Exception:
            pass
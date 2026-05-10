import asyncio
import os
import shutil
import tempfile
import json
from asyncio.subprocess import PIPE
from dataclasses import dataclass
from typing import Optional

from aiogram import Bot
from aiogram.types import FSInputFile

from storage import Storage


YT_DLP = os.environ.get("YTDLP_PATH", "yt-dlp")


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
            try:
                await self._process(entry)
            except Exception as exc:
                await self._safe_reply(entry.chat_id, f"error: {exc}")
            finally:
                self._cleanup(entry)
                self.current = None
                self.queue.task_done()

    async def enqueue(self, entry: DownloadEntry):
        await self.queue.put(entry)

    async def cancel_current(self, chat_id: int) -> bool:
        if not self.current or self.current.chat_id != chat_id:
            return False
        if self.current.proc and self.current.proc.returncode is None:
            self.current.proc.kill()
            return True
        return False

    async def get_video_formats(self, url: str) -> list[dict]:
        """Fetch available video formats from yt-dlp."""
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
                return video_formats[:10]  # Return top 10 formats
        except Exception:
            pass
        return []

    async def _process(self, entry: DownloadEntry):
        entry.workdir = tempfile.mkdtemp(prefix="ytdlp_")
        output_template = os.path.join(entry.workdir, "%(title)s.%(ext)s")
        args = [YT_DLP, "--no-playlist", "-o", output_template]
        if entry.fmt in ("mp3", "audio"):
            args += ["-x", "--audio-format", "mp3"]
        elif entry.fmt == "video" and entry.format_id:
            args += ["-f", entry.format_id]
        args.append(entry.url)

        proc = await asyncio.create_subprocess_exec(*args, stdout=PIPE, stderr=PIPE)
        entry.proc = proc
        _, stderr = await proc.communicate()
        entry.proc = None

        if proc.returncode != 0:
            raise RuntimeError(stderr.decode(errors="ignore").strip() or "yt-dlp failed")

        file_path = self._find_downloaded_file(entry.workdir)
        if not file_path:
            raise RuntimeError("no file downloaded")

        await self._safe_reply(entry.chat_id, "Uploading...")
        await self.bot.send_document(entry.chat_id, FSInputFile(file_path))

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
            shutil.rmtree(entry.workdir, ignore_errors=True)

    async def _safe_reply(self, chat_id: int, text: str):
        try:
            await self.bot.send_message(chat_id, text)
        except Exception:
            pass
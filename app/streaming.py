import asyncio
import hashlib
import logging
import os
import shutil
import time
from dataclasses import dataclass
from typing import Dict, Optional

log = logging.getLogger("streaming")


class HlsUnavailableError(RuntimeError):
    """Raised when HLS streaming is disabled or not supported."""


class HlsGenerationError(RuntimeError):
    """Raised when HLS generation fails."""


@dataclass
class HlsSession:
    playlist_path: str
    directory: str


class HlsStreamManager:
    def __init__(
        self,
        base_dir: str,
        ffmpeg_path: Optional[str] = None,
        *,
        enabled: bool = True,
        ttl_seconds: int = 1800,
    ) -> None:
        self.base_dir = os.path.abspath(base_dir)
        self.ffmpeg_path = ffmpeg_path or "ffmpeg"
        self.enabled = enabled
        self._disabled_reason: Optional[str] = None
        self.ttl_seconds = max(ttl_seconds, 60)
        self._locks: Dict[str, asyncio.Lock] = {}
        self._last_cleanup = 0.0

        os.makedirs(self.base_dir, exist_ok=True)

        self._ffmpeg_exec = None

        if not self.enabled:
            self._disable("disabled_in_config")
        else:
            resolved = shutil.which(self.ffmpeg_path)
            if not resolved:
                log.warning("FFmpeg executable '%s' not found; disabling HLS streaming", self.ffmpeg_path)
                self._disable("ffmpeg_not_found")
            else:
                self._ffmpeg_exec = resolved
                log.info("Adaptive streaming enabled using ffmpeg binary at %s", resolved)

    def _disable(self, reason: str) -> None:
        if self.enabled:
            log.warning("Disabling adaptive streaming: %s", self._format_unavailable_reason(reason))
        self.enabled = False
        self._disabled_reason = reason

    def status_code(self) -> str:
        if self.enabled:
            return "available"
        return self._disabled_reason or "unavailable"

    def status_message(self) -> str:
        if self.enabled:
            return ""
        return self._format_unavailable_reason(self._disabled_reason)

    def _format_unavailable_reason(self, reason: Optional[str]) -> str:
        if reason == "disabled_in_config":
            return "Adaptive streaming is disabled in server configuration."
        if reason == "ffmpeg_not_found":
            return f"Adaptive streaming requires '{self.ffmpeg_path}' to be installed on the server."
        return "Adaptive streaming is currently unavailable."

    def _hash_component(self, value: str) -> str:
        return hashlib.sha1(value.encode("utf-8", "ignore")).hexdigest()

    def _stream_root(self, user_id: str, download_id: str) -> str:
        user_hash = self._hash_component(user_id)
        download_hash = self._hash_component(download_id)
        return os.path.join(self.base_dir, user_hash, download_hash)

    def _playlist_path(self, user_id: str, download_id: str) -> str:
        return os.path.join(self._stream_root(user_id, download_id), "index.m3u8")

    async def ensure_session(self, user_id: str, download_id: str, source_path: str) -> HlsSession:
        if not self.enabled:
            message = self._format_unavailable_reason(self._disabled_reason)
            log.debug(
                "Adaptive streaming requested while disabled (user=%s, download=%s): %s",
                user_id,
                download_id,
                message,
            )
            raise HlsUnavailableError(message)

        directory = self._stream_root(user_id, download_id)
        playlist_path = self._playlist_path(user_id, download_id)
        lock = self._locks.setdefault(directory, asyncio.Lock())

        await self._maybe_cleanup()

        async with lock:
            if self._is_fresh(playlist_path, source_path):
                self._touch(directory)
                return HlsSession(playlist_path=playlist_path, directory=directory)

            await self._generate_hls(directory, playlist_path, source_path)
            self._touch(directory)
            return HlsSession(playlist_path=playlist_path, directory=directory)

    def touch_session(self, user_id: str, download_id: str) -> None:
        directory = self._stream_root(user_id, download_id)
        self._touch(directory)

    def session_directory(self, user_id: str, download_id: str) -> str:
        return self._stream_root(user_id, download_id)

    def _is_fresh(self, playlist_path: str, source_path: str) -> bool:
        if not os.path.exists(playlist_path):
            return False
        try:
            playlist_mtime = os.path.getmtime(playlist_path)
            source_mtime = os.path.getmtime(source_path)
        except OSError:
            return False
        if playlist_mtime < source_mtime:
            return False
        if (time.time() - playlist_mtime) > self.ttl_seconds:
            return False
        return True

    async def _generate_hls(self, directory: str, playlist_path: str, source_path: str) -> None:
        try:
            if os.path.isdir(directory):
                shutil.rmtree(directory)
            os.makedirs(directory, exist_ok=True)
        except OSError as exc:
            raise HlsGenerationError(f"Failed to prepare HLS directory: {exc}")

        segment_pattern = os.path.join(directory, "segment-%05d.ts")
        ffmpeg_exec = self._ffmpeg_exec or self.ffmpeg_path
        cmd = [
            ffmpeg_exec,
            "-y",
            "-i",
            source_path,
            "-preset",
            "veryfast",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            "-f",
            "hls",
            "-hls_time",
            "4",
            "-hls_playlist_type",
            "vod",
            "-hls_segment_filename",
            segment_pattern,
            playlist_path,
        ]

        log.info("Starting ffmpeg HLS generation for %s", source_path)
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except FileNotFoundError:
            self._disable("ffmpeg_not_found")
            raise HlsUnavailableError(self._format_unavailable_reason(self._disabled_reason))
        except Exception as exc:
            raise HlsGenerationError(f"Failed to spawn ffmpeg: {exc}")

        assert process.stdout is not None
        stdout_chunks = []
        async for chunk in process.stdout:
            text = chunk.decode(errors="ignore").strip()
            if text:
                stdout_chunks.append(text)

        return_code = await process.wait()
        if return_code != 0:
            output = "\n".join(stdout_chunks[-10:])
            raise HlsGenerationError(
                f"FFmpeg exited with code {return_code}. Output:\n{output}"
            )

        if not os.path.exists(playlist_path):
            raise HlsGenerationError("FFmpeg did not produce a playlist")

    async def _maybe_cleanup(self) -> None:
        now = time.time()
        if (now - self._last_cleanup) < 300:
            return
        self._last_cleanup = now
        await asyncio.get_running_loop().run_in_executor(None, self._cleanup_expired)

    def _cleanup_expired(self) -> None:
        for user_dir in self._iter_dirs(self.base_dir):
            for download_dir in self._iter_dirs(user_dir):
                try:
                    mtime = os.path.getmtime(download_dir)
                except OSError:
                    continue
                if (time.time() - mtime) > self.ttl_seconds:
                    try:
                        shutil.rmtree(download_dir, ignore_errors=True)
                    except Exception:
                        log.debug("Failed to remove expired HLS directory %s", download_dir, exc_info=True)

    def _touch(self, directory: str) -> None:
        try:
            os.makedirs(directory, exist_ok=True)
            now = time.time()
            os.utime(directory, times=(now, now))
        except OSError:
            pass

    def _iter_dirs(self, parent: str):
        try:
            with os.scandir(parent) as entries:
                for entry in entries:
                    if entry.is_dir():
                        yield entry.path
        except FileNotFoundError:
            return

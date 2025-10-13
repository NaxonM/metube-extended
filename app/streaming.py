import asyncio
import hashlib
import logging
import os
import shutil
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Dict, Optional

import psutil

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
        cpu_limit_percent: Optional[float] = None,
        memory_limit_percent: Optional[float] = None,
    ) -> None:
        self.base_dir = os.path.abspath(base_dir)
        self.ffmpeg_path = ffmpeg_path or "ffmpeg"
        self.enabled = enabled
        self._disabled_reason: Optional[str] = None
        self.ttl_seconds = max(ttl_seconds, 60)
        self._locks: Dict[str, asyncio.Lock] = {}
        self._last_cleanup = 0.0

        self.cpu_limit_percent = cpu_limit_percent if cpu_limit_percent and cpu_limit_percent > 0 else None
        self.memory_limit_percent = memory_limit_percent if memory_limit_percent and memory_limit_percent > 0 else None
        self.monitor_interval = 1.0
        self.cpu_cooldown_base = 0.5
        self.cpu_cooldown_min = 0.1
        self.cpu_cooldown_max = 2.0
        self._limit_messages: Dict[int, str] = {}
        self._cpu_limit_total = None
        self._memory_limit_bytes = None

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
        
        log.debug("FFmpeg executable resolved to: %s", self._ffmpeg_exec)

        self._cpu_limit_total = self._compute_cpu_limit()
        self._memory_limit_bytes = self._compute_memory_limit()

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

    def _compute_cpu_limit(self) -> Optional[float]:
        if not self.cpu_limit_percent:
            return None
        try:
            cpu_total = psutil.cpu_count(logical=True)
        except Exception:
            cpu_total = None
        if not cpu_total:
            cpu_total = os.cpu_count() or 1
        return float(cpu_total) * 100.0 * (self.cpu_limit_percent / 100.0)

    def _compute_memory_limit(self) -> Optional[int]:
        if not self.memory_limit_percent:
            return None
        try:
            total = psutil.virtual_memory().total
        except Exception:
            total = 0
        if not total:
            return None
        return int(total * (self.memory_limit_percent / 100.0))

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

        monitor_task = None
        if self._cpu_limit_total is not None or self._memory_limit_bytes is not None:
            monitor_task = asyncio.create_task(self._monitor_process(process, source_path))

        stdout_chunks = []
        async for chunk in process.stdout:
            text = chunk.decode(errors="ignore").strip()
            if text:
                stdout_chunks.append(text)

        return_code = await process.wait()

        if monitor_task is not None:
            with suppress(asyncio.CancelledError):
                await monitor_task

        limit_message = None
        if process.pid is not None:
            limit_message = self._limit_messages.pop(process.pid, None)

        if limit_message:
            raise HlsUnavailableError(limit_message)

        if return_code != 0:
            output = "\n".join(stdout_chunks[-10:])
            raise HlsGenerationError(
                f"FFmpeg exited with code {return_code}. Output:\n{output}"
            )

        if not os.path.exists(playlist_path):
            raise HlsGenerationError("FFmpeg did not produce a playlist")

        log.info("FFmpeg HLS generation completed for %s", source_path)

    async def _monitor_process(self, process: asyncio.subprocess.Process, source_path: str) -> None:
        if process.pid is None:
            return
        try:
            ps_proc = psutil.Process(process.pid)
        except psutil.Error:
            return

        try:
            ps_proc.cpu_percent(interval=None)
        except psutil.Error:
            return

        interval = max(self.monitor_interval, 0.2)

        while True:
            if process.returncode is not None:
                return
            await asyncio.sleep(interval)

            try:
                cpu_usage = ps_proc.cpu_percent(interval=None)
            except psutil.Error:
                return

            rss_bytes = None
            if self._memory_limit_bytes is not None:
                try:
                    rss_bytes = ps_proc.memory_info().rss
                except psutil.Error:
                    rss_bytes = None

            if (
                self._memory_limit_bytes is not None
                and rss_bytes is not None
                and rss_bytes > self._memory_limit_bytes
            ):
                message = self._format_memory_limit_message(rss_bytes, self._memory_limit_bytes)
                log.warning(
                    "FFmpeg HLS job for %s exceeded memory limit (rss=%s limit=%s); terminating",
                    source_path,
                    self._format_bytes(rss_bytes),
                    self._format_bytes(self._memory_limit_bytes),
                )
                self._limit_messages[process.pid] = message
                with suppress(psutil.Error):
                    ps_proc.terminate()
                await asyncio.sleep(0.2)
                if process.returncode is None:
                    with suppress(psutil.Error):
                        ps_proc.kill()
                return

            if self._cpu_limit_total is not None and cpu_usage is not None and cpu_usage > self._cpu_limit_total:
                pause = self._compute_cpu_pause(cpu_usage, self._cpu_limit_total)
                if pause <= 0:
                    continue
                log.debug(
                    "Throttling FFmpeg CPU usage for %s (usage=%.1f%% limit=%.1f%% pause=%.2fs)",
                    source_path,
                    cpu_usage,
                    self._cpu_limit_total,
                    pause,
                )
                try:
                    ps_proc.suspend()
                except psutil.Error:
                    continue
                try:
                    await asyncio.sleep(pause)
                finally:
                    with suppress(psutil.Error):
                        ps_proc.resume()

    def _compute_cpu_pause(self, usage: float, limit: float) -> float:
        if limit <= 0:
            return self.cpu_cooldown_base
        excess_ratio = max(usage / limit - 1.0, 0.0)
        if excess_ratio <= 0:
            return 0.0
        pause = self.cpu_cooldown_base * (1.0 + excess_ratio)
        return max(self.cpu_cooldown_min, min(pause, self.cpu_cooldown_max))

    def _format_memory_limit_message(self, rss: int, limit: int) -> str:
        return (
            "Adaptive streaming stopped because transcoding consumed "
            f"{self._format_bytes(rss)} of memory (limit {self._format_bytes(limit)})."
        )

    @staticmethod
    def _format_bytes(value: int) -> str:
        units = ["B", "KB", "MB", "GB", "TB"]
        number = float(value)
        for unit in units:
            if number < 1024.0 or unit == units[-1]:
                return f"{number:.1f}{unit}"
            number /= 1024.0

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

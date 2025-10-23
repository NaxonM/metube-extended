import asyncio
import json
import logging
import os
import time
import uuid
from collections import OrderedDict
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from seedrcc import AsyncSeedr, models
from seedrcc.exceptions import AuthenticationError, SeedrError

from seedr_credentials import SeedrCredentialStore
from ytdl import DownloadInfo, DownloadQueue

log = logging.getLogger("seedr")


def _sanitize_filename(candidate: str) -> str:
    candidate = candidate.replace("\0", "")
    name = candidate.strip().replace("\\", "/").split("/")[-1]
    return name or f"seedr-download-{uuid.uuid4().hex}"


def _ensure_unique_path(base_directory: str, filename: str) -> Tuple[str, str]:
    name, ext = os.path.splitext(filename)
    counter = 1
    candidate = filename
    while os.path.exists(os.path.join(base_directory, candidate)):
        candidate = f"{name}_{counter}{ext}"
        counter += 1
    return candidate, os.path.join(base_directory, candidate)


def _progress_to_percent(progress: str) -> Optional[float]:
    if not progress:
        return None
    text = progress.strip()
    if text.endswith('%'):
        text = text[:-1]
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    if value < 0 or value > 1000:
        return None
    return value


def _flatten_folders(folders: List[models.Folder]) -> List[models.Folder]:
    stack = list(folders)
    result: List[models.Folder] = []
    while stack:
        folder = stack.pop()
        result.append(folder)
        stack.extend(folder.folders)
    return result


class SeedrJob:
    def __init__(
        self,
        info: DownloadInfo,
        magnet_link: Optional[str] = None,
        torrent_file: Optional[str] = None,
        folder_id: str = "-1",
    ) -> None:
        self.info = info
        self.magnet_link = magnet_link
        self.torrent_file = torrent_file
        self.folder_id = folder_id
        self.seedr_torrent_id: Optional[int] = None
        self.seedr_folder_id: Optional[int] = None
        self.seedr_folder_name: Optional[str] = None
        self.archive_url: Optional[str] = None
        self.file_path: Optional[str] = None
        self._task: Optional[asyncio.Task] = None
        self._cancel_requested = False
        self._added_at = time.time()
        self.local_torrent_path: Optional[str] = torrent_file if torrent_file and os.path.exists(torrent_file) else None

    def cancel(self) -> None:
        self._cancel_requested = True

    @property
    def canceled(self) -> bool:
        return self._cancel_requested

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()


class SeedrDownloadManager:
    POLL_INTERVAL = 10
    ARCHIVE_MAX_ATTEMPTS = 6
    ARCHIVE_RETRY_INTERVAL = 5

    def __init__(
        self,
        config,
        notifier,
        base_queue: DownloadQueue,
        state_dir: str,
        user_id: str,
        token_store: SeedrCredentialStore,
        max_history_items: int = 200,
    ) -> None:
        self.config = config
        self.notifier = notifier
        self.base_queue = base_queue
        self.user_id = user_id
        self.token_store = token_store
        self.state_dir = os.path.join(state_dir, "seedr")
        os.makedirs(self.state_dir, exist_ok=True)
        self.completed_state_path = os.path.join(self.state_dir, "completed.json")

        self.queue: "OrderedDict[str, SeedrJob]" = OrderedDict()
        self.pending: "OrderedDict[str, SeedrJob]" = OrderedDict()
        self.done: "OrderedDict[str, SeedrJob]" = OrderedDict()
        self.max_history_items = max_history_items if max_history_items is not None else 200

        self._client: Optional[AsyncSeedr] = None
        self._client_lock = asyncio.Lock()
        self._account_snapshot: Optional[Dict[str, Any]] = None
        self._semaphore = asyncio.Semaphore(1)

    async def initialize(self) -> None:
        self._load_completed()
        if self.max_history_items >= 0:
            if self._enforce_history_limit():
                self._persist_completed()

    # ------------------------------------------------------------------
    # Queue helpers
    # ------------------------------------------------------------------
    def get(self) -> Tuple[List[Tuple[str, DownloadInfo]], List[Tuple[str, DownloadInfo]]]:
        queue_items = [(key, job.info) for key, job in self.queue.items()] + [
            (key, job.info) for key, job in self.pending.items()
        ]
        done_items = [(key, job.info) for key, job in self.done.items()]
        done_items.reverse()
        return queue_items, done_items

    def get_done(self, download_id: str) -> Optional[SeedrJob]:
        return self.done.get(download_id)

    async def add_job(
        self,
        *,
        magnet_link: Optional[str] = None,
        torrent_file: Optional[str] = None,
        title: Optional[str] = None,
        folder: str = "",
        custom_name_prefix: str = "",
        auto_start: bool = True,
        folder_id: str = "-1",
    ) -> Dict[str, Any]:
        if not magnet_link and not torrent_file:
            return {"status": "error", "msg": "Provide a magnet link or torrent file."}

        record = self.token_store.load_token()
        if not record:
            return {"status": "error", "msg": "Seedr account is not connected."}

        job_id = uuid.uuid4().hex
        storage_key = f"seedr:{job_id}"
        display_title = title or self._infer_display_title(magnet_link, torrent_file)

        info = DownloadInfo(
            job_id,
            display_title,
            storage_key,
            "seedr",
            "seedr",
            folder or "",
            custom_name_prefix or "",
            error=None,
            entry=None,
            playlist_item_limit=0,
            cookiefile=None,
            user_id=self.user_id,
            original_url=magnet_link or torrent_file or "",
            provider="seedr",
        )
        info.status = "pending"
        info.percent = 0.0
        info.speed = None
        info.eta = None
        info.filename = display_title

        job = SeedrJob(
            info,
            magnet_link=magnet_link,
            torrent_file=torrent_file,
            folder_id=folder_id or "-1",
        )
        self.pending[storage_key] = job
        await self.notifier.added(info)

        if auto_start:
            await self.start_jobs([storage_key])
        return {"status": "ok", "id": storage_key}

    async def start_jobs(self, ids: Iterable[str]) -> Dict[str, Any]:
        for storage_key in ids:
            job = self.pending.pop(storage_key, None)
            if not job:
                continue
            self.queue[storage_key] = job
            await self._start_job(storage_key, job)
        return {"status": "ok"}

    async def cancel(self, ids: Iterable[str]) -> Dict[str, Any]:
        for storage_key in ids:
            if storage_key in self.pending:
                job = self.pending.pop(storage_key)
                job.info.status = "canceled"
                self._cleanup_local_torrent(job)
                await self.notifier.canceled(storage_key)
                continue
            job = self.queue.get(storage_key)
            if job:
                job.cancel()
        return {"status": "ok"}

    async def clear(self, ids: Iterable[str]) -> Dict[str, Any]:
        deleted, missing, errors = [], [], {}
        for storage_key in ids:
            job = self.done.get(storage_key)
            if not job:
                continue

            file_path = job.file_path
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    deleted.append(job.info.filename or job.info.title)
                except OSError as exc:
                    errors[storage_key] = str(exc)
                    continue
            else:
                missing.append(job.info.filename or job.info.title)

            self.done.pop(storage_key, None)
            await self.notifier.cleared(storage_key)

        self._persist_completed()
        result: Dict[str, Any] = {"status": "ok", "deleted": deleted, "missing": missing}
        if errors:
            result.update({"status": "error", "errors": errors, "msg": "Some files could not be removed from disk."})
        return result

    async def rename(self, storage_key: str, new_name: str) -> Dict[str, Any]:
        job = self.done.get(storage_key)
        if not job:
            return {"status": "error", "msg": "Download not found."}

        if not job.file_path or not os.path.exists(job.file_path):
            return {"status": "error", "msg": "Original file no longer exists."}

        directory = os.path.dirname(job.file_path)
        sanitized = _sanitize_filename(new_name)
        target_path = os.path.join(directory, sanitized)
        if os.path.exists(target_path):
            return {"status": "error", "msg": "A file with the requested name already exists."}

        try:
            os.rename(job.file_path, target_path)
        except OSError as exc:
            return {"status": "error", "msg": f"Failed to rename file: {exc}"}

        job.file_path = target_path
        job.info.filename = sanitized
        job.info.title = sanitized
        try:
            job.info.size = os.path.getsize(target_path)
        except OSError:
            pass
        await self.notifier.renamed(job.info)
        self._persist_completed()
        return {"status": "ok", "filename": sanitized, "title": sanitized}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    async def _start_job(self, storage_key: str, job: SeedrJob) -> None:
        job.info.status = "preparing"
        job.info.msg = "Preparing Seedr transfer"
        await self.notifier.updated(job.info)

        async def runner() -> None:
            async with self._semaphore:
                await self._run_job(storage_key, job)

        job._task = asyncio.create_task(runner())

    async def _run_job(self, storage_key: str, job: SeedrJob) -> None:
        try:
            client = await self._ensure_client()
        except AuthenticationError:
            await self._finalize_error(storage_key, job, "Seedr account credentials are invalid.")
            return
        except SeedrError as exc:
            await self._finalize_error(storage_key, job, f"Failed to connect to Seedr: {exc}")
            return
        except Exception as exc:  # pragma: no cover - unexpected
            await self._finalize_error(storage_key, job, f"Unexpected Seedr error: {exc}")
            return

        if job.canceled:
            self.queue.pop(storage_key, None)
            return

        if job.magnet_link:
            add_kwargs = {"magnet_link": job.magnet_link}
        elif job.torrent_file:
            add_kwargs = {"torrent_file": job.torrent_file}
        else:
            await self._finalize_error(storage_key, job, "Job has no magnet link or torrent file.")
            return

        job.info.status = "uploading"
        job.info.msg = "Adding torrent to Seedr"
        await self.notifier.updated(job.info)

        try:
            add_result = await client.add_torrent(folder_id=job.folder_id, **add_kwargs)
        except AuthenticationError as exc:
            self._invalidate_client()
            await self._finalize_error(storage_key, job, f"Seedr authentication failed: {exc}")
            return
        except SeedrError as exc:
            await self._finalize_error(storage_key, job, f"Failed to add torrent: {exc}")
            return
        except Exception as exc:  # pragma: no cover
            await self._finalize_error(storage_key, job, f"Unexpected error adding torrent: {exc}")
            return

        self._cleanup_local_torrent(job)
        job.seedr_torrent_id = add_result.user_torrent_id
        job.info.status = "downloading"
        job.info.msg = "Waiting for Seedr to fetch torrent"
        await self.notifier.updated(job.info)

        torrent_data = await self._monitor_torrent(client, storage_key, job)
        if not torrent_data:
            await self._cleanup_seedr(client, job)
            if job.canceled:
                self.queue.pop(storage_key, None)
                await self.notifier.canceled(storage_key)
            return

        torrent, contents = torrent_data
        job.seedr_folder_name = torrent.folder or torrent.name

        target_folder = self._resolve_folder(contents.folders, job.seedr_folder_name)
        if not target_folder:
            await self._finalize_error(storage_key, job, "Unable to locate Seedr folder for completed torrent.")
            await self._cleanup_seedr(client, job)
            return

        job.seedr_folder_id = target_folder.id

        if len(target_folder.files) == 1 and not target_folder.folders:
            success = await self._download_seedr_file(client, job, target_folder.files[0])
        else:
            archive = await self._prepare_archive(client, storage_key, job, target_folder)
            if not archive:
                return

            job.archive_url = archive.archive_url
            success = await self._download_archive(job, target_folder, archive)

        if not success:
            return

        await self._cleanup_seedr(client, job)
        self.queue.pop(storage_key, None)
        self.done[storage_key] = job
        self._persist_completed()
        await self.notifier.completed(job.info)

    async def _monitor_torrent(
        self,
        client: AsyncSeedr,
        storage_key: str,
        job: SeedrJob,
    ) -> Optional[Tuple[models.Torrent, models.ListContentsResult]]:
        while not job.canceled:
            try:
                contents = await client.list_contents()
            except AuthenticationError as exc:
                self._invalidate_client()
                await self._finalize_error(storage_key, job, f"Seedr authentication failed: {exc}")
                return None
            except SeedrError as exc:
                await asyncio.sleep(self.POLL_INTERVAL)
                log.debug("Seedr list_contents failed for %s: %s", self.user_id, exc)
                continue

            torrent = None
            magnet_hash = add_hash_from_magnet(job.magnet_link) if job.magnet_link else None
            for item in contents.torrents:
                if job.seedr_torrent_id and item.id == job.seedr_torrent_id:
                    torrent = item
                    break
                if magnet_hash and item.hash and item.hash.upper() == magnet_hash:
                    torrent = item
                    break

            if torrent is None:
                if job.seedr_torrent_id:
                    await self._finalize_error(storage_key, job, "Seedr torrent disappeared before completion.")
                    return None
                await asyncio.sleep(self.POLL_INTERVAL)
                continue

            progress = _progress_to_percent(torrent.progress)
            if progress is not None:
                job.info.percent = progress
            job.info.msg = f"Seedr progress: {torrent.progress}" if torrent.progress else "Seedr downloading"
            await self.notifier.updated(job.info)

            if progress is not None and progress >= 100:
                return torrent, contents

            await asyncio.sleep(self.POLL_INTERVAL)

        log.info("Seedr job %s canceled before completion", storage_key)
        job.info.status = "canceled"
        job.info.msg = "Seedr job canceled"
        await self.notifier.updated(job.info)
        return None

    async def _prepare_archive(
        self,
        client: AsyncSeedr,
        storage_key: str,
        job: SeedrJob,
        folder: models.Folder,
    ) -> Optional[models.CreateArchiveResult]:
        attempt = 0
        while attempt < self.ARCHIVE_MAX_ATTEMPTS:
            attempt += 1
            try:
                archive = await client.create_archive(str(folder.id))
            except SeedrError as exc:
                log.error("Failed to create Seedr archive for folder %s: %s", folder.id, exc)
                await asyncio.sleep(self.ARCHIVE_RETRY_INTERVAL)
                continue

            if archive and archive.result and archive.archive_url:
                return archive

            await asyncio.sleep(self.ARCHIVE_RETRY_INTERVAL)

        await self._finalize_error(storage_key, job, "Seedr archive is not ready yet. Please try again later.")
        return None

    async def _download_archive(
        self,
        job: SeedrJob,
        folder: models.Folder,
        archive: models.CreateArchiveResult,
    ) -> bool:
        directory = self.base_queue._resolve_download_directory(job.info)
        if not directory:
            await self._finalize_error(job.info.url, job, "Download directory unavailable.")
            return False
        os.makedirs(directory, exist_ok=True)

        folder_name = folder.fullname or folder.name or job.info.title or f"seedr-{job.info.id}"
        filename = _sanitize_filename(folder_name)
        if not filename:
            filename = f"seedr-{job.info.id}"
        if not filename.lower().endswith('.zip'):
            filename = f"{filename}.zip"
        filename, path = _ensure_unique_path(directory, filename)

        job.info.status = "downloading"
        job.info.msg = "Downloading archive from Seedr"
        job.info.filename = filename
        job.info.title = filename
        job.info.percent = None
        job.info.speed = None
        job.info.eta = None
        await self.notifier.updated(job.info)

        try:
            async with httpx.AsyncClient(timeout=None, follow_redirects=True) as session:
                async with session.stream("GET", archive.archive_url) as response:
                    response.raise_for_status()
                    total = response.headers.get("Content-Length")
                    total_bytes = int(total) if total and total.isdigit() else None
                    downloaded = 0
                    start_time = time.monotonic()

                    with open(path, "wb") as fh:
                        async for chunk in response.aiter_bytes(chunk_size=256 * 1024):
                            if job.canceled:
                                raise asyncio.CancelledError()
                            if not chunk:
                                continue
                            fh.write(chunk)
                            downloaded += len(chunk)
                            job.info.size = downloaded
                            elapsed = max(time.monotonic() - start_time, 1e-6)
                            job.info.speed = downloaded / elapsed
                            if total_bytes:
                                job.info.percent = (downloaded / total_bytes) * 100
                                remaining = max(total_bytes - downloaded, 0)
                                job.info.eta = int(remaining / job.info.speed) if job.info.speed else None
                            await self.notifier.updated(job.info)
        except asyncio.CancelledError:
            job.info.status = "canceled"
            job.info.msg = "Download canceled"
            await self.notifier.updated(job.info)
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
            return False
        except Exception as exc:
            await self._finalize_error(job.info.url, job, f"Failed to download archive: {exc}")
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
            return False

        job.file_path = path
        try:
            job.info.size = os.path.getsize(path)
        except OSError:
            pass
        job.info.status = "finished"
        job.info.msg = "Seedr transfer complete"
        job.info.percent = 100.0
        job.info.speed = None
        job.info.eta = None
        return True

    async def _download_seedr_file(self, client: AsyncSeedr, job: SeedrJob, file: models.File) -> bool:
        try:
            fetch = await client.fetch_file(str(file.folder_file_id))
        except SeedrError as exc:
            await self._finalize_error(job.info.url, job, f"Failed to fetch Seedr file: {exc}")
            return False

        if not fetch.result or not fetch.url:
            await self._finalize_error(job.info.url, job, "Seedr did not return a download link for the file.")
            return False

        directory = self.base_queue._resolve_download_directory(job.info)
        if not directory:
            await self._finalize_error(job.info.url, job, "Download directory unavailable.")
            return False
        os.makedirs(directory, exist_ok=True)

        base_name = fetch.name or file.name or job.info.title or f"seedr-{job.info.id}"
        filename = _sanitize_filename(base_name)
        if not filename:
            filename = f"seedr-{job.info.id}"
        filename, path = _ensure_unique_path(directory, filename)

        job.info.status = "downloading"
        job.info.msg = "Downloading from Seedr"
        job.info.filename = filename
        job.info.title = filename
        job.info.percent = 0.0
        job.info.speed = None
        job.info.eta = None
        job.info.size = file.size
        await self.notifier.updated(job.info)

        try:
            async with httpx.AsyncClient(timeout=None, follow_redirects=True) as session:
                async with session.stream("GET", fetch.url) as response:
                    response.raise_for_status()
                    total = response.headers.get("Content-Length")
                    total_bytes = int(total) if total and total.isdigit() else (file.size or None)
                    downloaded = 0
                    start_time = time.monotonic()

                    with open(path, "wb") as fh:
                        async for chunk in response.aiter_bytes(chunk_size=256 * 1024):
                            if job.canceled:
                                raise asyncio.CancelledError()
                            if not chunk:
                                continue
                            fh.write(chunk)
                            downloaded += len(chunk)
                            job.info.size = downloaded
                            elapsed = max(time.monotonic() - start_time, 1e-6)
                            job.info.speed = downloaded / elapsed
                            if total_bytes:
                                job.info.percent = (downloaded / total_bytes) * 100
                                remaining = max(total_bytes - downloaded, 0)
                                job.info.eta = int(remaining / job.info.speed) if job.info.speed else None
                            await self.notifier.updated(job.info)
        except asyncio.CancelledError:
            job.info.status = "canceled"
            job.info.msg = "Download canceled"
            await self.notifier.updated(job.info)
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
            return False
        except Exception as exc:
            await self._finalize_error(job.info.url, job, f"Failed to download Seedr file: {exc}")
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
            return False

        job.file_path = path
        try:
            job.info.size = os.path.getsize(path)
        except OSError:
            pass
        job.info.status = "finished"
        job.info.msg = "Seedr transfer complete"
        job.info.percent = 100.0
        job.info.speed = None
        job.info.eta = None
        return True

    async def _cleanup_seedr(self, client: AsyncSeedr, job: SeedrJob) -> None:
        # Attempt to remove torrent and folder to free space
        if job.seedr_torrent_id is not None:
            with suppress_seedr_error():
                await client.delete_torrent(str(job.seedr_torrent_id))
        if job.seedr_folder_id is not None:
            with suppress_seedr_error():
                await client.delete_folder(str(job.seedr_folder_id))
        self._cleanup_local_torrent(job)

    async def _ensure_client(self) -> AsyncSeedr:
        async with self._client_lock:
            if self._client is not None:
                return self._client

            record = self.token_store.load_token()
            if not record:
                raise AuthenticationError("Seedr account not connected")

            self._account_snapshot = record.account

            def _on_refresh(token):
                try:
                    self.token_store.save_token(token, self._account_snapshot or {})
                except Exception as exc:  # pragma: no cover
                    log.error("Failed to persist refreshed Seedr token for %s: %s", self.user_id, exc)

            self._client = AsyncSeedr(record.token, on_token_refresh=_on_refresh)
            return self._client

    def _invalidate_client(self) -> None:
        client = self._client
        self._client = None
        if client is not None:
            try:
                asyncio.create_task(client.close())
            except RuntimeError:
                # Event loop may not be running; close synchronously
                try:
                    loop = asyncio.get_event_loop()
                    loop.create_task(client.close())
                except Exception:
                    pass

    async def _finalize_error(self, storage_key: str, job: SeedrJob, message: str) -> None:
        job.info.status = "error"
        job.info.msg = message
        await self.notifier.updated(job.info)
        self.queue.pop(storage_key, None)
        self.done[storage_key] = job
        self._persist_completed()
        self._cleanup_local_torrent(job)

    def _resolve_folder(self, folders: List[models.Folder], target_name: Optional[str]) -> Optional[models.Folder]:
        if target_name is None:
            return None
        normalized = target_name.strip().lower()
        for folder in _flatten_folders(folders):
            if folder.name.strip().lower() == normalized:
                return folder
        return None

    def _load_completed(self) -> None:
        if not os.path.exists(self.completed_state_path):
            return
        try:
            with open(self.completed_state_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            log.error("Failed to load Seedr completed history for %s: %s", self.user_id, exc)
            return

        for record in data:
            try:
                info = DownloadInfo(
                    record["id"],
                    record.get("title"),
                    record["url"],
                    record.get("quality", "seedr"),
                    record.get("format", "seedr"),
                    record.get("folder", ""),
                    record.get("custom_name_prefix", ""),
                    error=record.get("error"),
                    entry=None,
                    playlist_item_limit=0,
                    cookiefile=None,
                    user_id=self.user_id,
                    original_url=record.get("original_url"),
                    provider="seedr",
                )
            except Exception as exc:
                log.warning("Skipping corrupted Seedr history record: %s", exc)
                continue

            info.filename = record.get("filename")
            info.status = record.get("status", "finished")
            info.msg = record.get("msg")
            info.percent = record.get("percent")
            info.size = record.get("size")
            info.timestamp = record.get("timestamp", time.time_ns())
            job = SeedrJob(info, magnet_link=None, torrent_file=None)
            job.file_path = record.get("file_path")
            job.seedr_torrent_id = record.get("seedr_torrent_id")
            job.seedr_folder_id = record.get("seedr_folder_id")
            job.seedr_folder_name = record.get("seedr_folder_name")
            job.local_torrent_path = None
            self.done[info.url] = job

    def _persist_completed(self) -> None:
        self._enforce_history_limit()
        data = []
        for storage_key, job in self.done.items():
            info = job.info
            data.append(
                {
                    "id": info.id,
                    "url": storage_key,
                    "original_url": info.original_url,
                    "title": info.title,
                    "filename": info.filename,
                    "folder": info.folder,
                    "size": info.size,
                    "status": info.status,
                    "msg": info.msg,
                    "timestamp": info.timestamp,
                    "file_path": job.file_path,
                    "quality": info.quality,
                    "format": info.format,
                    "custom_name_prefix": info.custom_name_prefix,
                    "seedr_torrent_id": job.seedr_torrent_id,
                    "seedr_folder_id": job.seedr_folder_id,
                    "seedr_folder_name": job.seedr_folder_name,
                    "percent": info.percent,
                }
            )

        temp_path = f"{self.completed_state_path}.tmp"
        try:
            with open(temp_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            os.replace(temp_path, self.completed_state_path)
        except OSError as exc:
            log.error("Failed to persist Seedr history for %s: %s", self.user_id, exc)

    def _enforce_history_limit(self) -> bool:
        limit = self.max_history_items
        if limit is None:
            return False
        changed = False
        if limit <= 0:
            if self.done:
                self.done.clear()
                changed = True
        else:
            while len(self.done) > limit:
                self.done.popitem(last=False)
                changed = True
        return changed

    def _cleanup_local_torrent(self, job: SeedrJob) -> None:
        path = job.local_torrent_path
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
        job.local_torrent_path = None

    def _infer_display_title(
        self,
        magnet_link: Optional[str],
        torrent_file: Optional[str],
    ) -> str:
        if torrent_file:
            name = os.path.basename(torrent_file)
            if name:
                return name.strip() or "Seedr torrent"

        if magnet_link:
            try:
                parsed = urlparse(magnet_link)
                params = parse_qs(parsed.query)
                if params.get("dn"):
                    display = unquote(params["dn"][0]).strip()
                    if display:
                        sanitized = " ".join(display.split())
                        if sanitized:
                            return sanitized[:200]
            except Exception:
                pass
        return "Seedr magnet"


class suppress_seedr_error:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            return True
        if issubclass(exc_type, SeedrError):
            log.debug("Seedr cleanup error ignored: %s", exc)
            return True
        return False


def add_hash_from_magnet(magnet: str) -> Optional[str]:
    if not magnet or "xt=urn:btih:" not in magnet:
        return None
    try:
        fragment = magnet.split("xt=urn:btih:", 1)[1]
        tail = fragment.split("&", 1)[0]
        return tail.upper()
    except Exception:
        return None

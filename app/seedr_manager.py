import asyncio
import json
import logging
import os
import time
import uuid
from collections import OrderedDict
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from seedrcc import AsyncSeedr, Token, models
from seedrcc.exceptions import APIError, AuthenticationError, SeedrError

from seedr_credentials import SeedrCredentialStore
from ytdl import DownloadInfo, DownloadQueue, build_download_storage_key

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
    lowered = text.lower()
    if any(token in lowered for token in ("done", "finished", "seeding", "complete")):
        return 100.0
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


def _summarize_seedr_error(exc: SeedrError) -> str:
    message = (str(exc) or "").strip()
    payload: Dict[str, Any] = {}
    payload_text = ""
    code: Optional[int] = None

    if isinstance(exc, APIError):
        code = exc.code
        response = getattr(exc, "response", None)
        if response is not None:
            try:
                raw = response.json()
                if isinstance(raw, dict):
                    payload = raw
            except Exception:
                try:
                    payload_text = response.text.strip()
                except Exception:
                    payload_text = ""
        if payload and code is None:
            payload_code = payload.get("code")
            if isinstance(payload_code, int):
                code = payload_code

        candidates: List[str] = []
        if message and message.lower() != "unknown api error":
            candidates.append(message)
        else:
            candidates.append("")

        if payload:
            for key in ("error_description", "error", "message", "detail", "details", "reason"):
                value = payload.get(key)
                if value:
                    candidates.append(str(value))
        if payload_text:
            candidates.append(payload_text)

        for candidate in candidates:
            cleaned = (candidate or "").strip()
            if cleaned and cleaned.lower() != "unknown api error":
                message = cleaned
                break

        if (not message) or message.lower() == "unknown api error":
            search_space = payload_text.lower() if payload_text else json.dumps(payload).lower() if payload else ""
            if any(term in search_space for term in ("space", "storage", "quota", "full")):
                message = "Seedr storage quota exceeded. Free up space or upgrade your plan before retrying."
            elif "bandwidth" in search_space:
                message = "Seedr bandwidth quota exceeded. Please wait for the quota to reset or upgrade your plan."
            else:
                message = "Seedr rejected this torrent. It may exceed your available storage or bandwidth."

        if code is not None and "code" not in message.lower():
            message = f"{message} (code {code})"

    if not message:
        return "Seedr request failed."
    return message


def _format_seedr_error(prefix: str, exc: SeedrError) -> str:
    detail = _summarize_seedr_error(exc)
    return f"{prefix}: {detail}" if prefix else detail


def _summarize_seedr_add_failure(payload: Optional[Dict[str, Any]]) -> str:
    if not payload:
        return "Seedr could not add this torrent."

    candidates: List[str] = []
    for key in ("error_description", "error", "message", "msg", "detail", "details", "reason", "status_text"):
        value = payload.get(key)
        if value:
            candidates.append(str(value))

    message = ""
    for candidate in candidates:
        cleaned = candidate.strip()
        if cleaned and cleaned.lower() not in {"false", "true"}:
            message = cleaned
            break

    if not message and payload.get("result") is False:
        message = "Seedr reported a failure while adding this torrent."

    serialized = ""
    if not message:
        try:
            serialized = json.dumps(payload).lower()
        except Exception:
            serialized = ""
        if serialized:
            if any(term in serialized for term in ("space", "storage", "quota")):
                message = "Seedr storage quota exceeded. Free up space before retrying."
            elif "bandwidth" in serialized:
                message = "Seedr bandwidth quota exceeded. Please wait for the quota to reset or upgrade your plan."

    code = payload.get("code")
    if code is not None:
        if message:
            if "code" not in message.lower():
                message = f"{message} (code {code})"
        else:
            message = f"Seedr could not add this torrent (code {code})."

    return message or "Seedr could not add this torrent."


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
        self.stage: str = "queued"
        self.announced: bool = False
        self.expected_name: Optional[str] = None
        self.magnet_hash: Optional[str] = None
        self.seedr_file_id: Optional[int] = None
        self.fetch_started_at: Optional[float] = None
        self.last_progress_percent: Optional[float] = None
        self.last_progress_at: Optional[float] = None

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
    TORRENT_FETCH_TIMEOUT = 3 * 60 * 60  # Seedr enforces a 3-hour limit for free accounts
    TORRENT_STALL_TIMEOUT = 90 * 60      # Abort if no progress for 90 minutes; Seedr free tier can be slow
    MAX_STATUS_ERRORS = 30               # Allow up to ~5 minutes of intermittent API failures

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
        self._last_account_refresh: float = 0.0

    async def initialize(self) -> None:
        self._load_completed()
        if self.max_history_items >= 0:
            if self._enforce_history_limit():
                self._persist_completed()

    async def account_summary(self, force: bool = False) -> Optional[Dict[str, Any]]:
        if not force and self._account_snapshot:
            return self._account_snapshot

        try:
            client = await self._ensure_client()
        except AuthenticationError:
            return None
        except SeedrError as exc:
            log.debug("Seedr account summary unavailable for %s: %s", self.user_id, _summarize_seedr_error(exc))
            return self._account_snapshot

        summary = await self._refresh_account_snapshot(client, persist=True)
        return summary or self._account_snapshot

    async def _announce_job(self, job: SeedrJob) -> None:
        if not job.announced:
            job.announced = True
            await self.notifier.added(job.info)

    async def _notify_update(self, job: SeedrJob) -> None:
        if job.announced:
            await self.notifier.updated(job.info)

    def _set_account_snapshot(self, summary: Optional[Dict[str, Any]], *, persist: bool = False, token: Optional[Token] = None) -> None:
        if summary is None:
            return
        self._account_snapshot = summary
        if persist:
            try:
                target_token = token
                if target_token is None:
                    record = self.token_store.load_token()
                    target_token = record.token if record else None
                if target_token is not None:
                    self.token_store.save_token(target_token, summary)
            except Exception as exc:  # pragma: no cover - persistence failures should not crash
                log.warning("Failed to persist Seedr account snapshot for %s: %s", self.user_id, exc)

    async def _refresh_account_snapshot(self, client: AsyncSeedr, *, persist: bool = False) -> Optional[Dict[str, Any]]:
        try:
            settings = await client.get_settings()
        except SeedrError as exc:
            log.debug("Seedr settings fetch failed for %s: %s", self.user_id, _summarize_seedr_error(exc))
            return self._account_snapshot

        memory: Optional[models.MemoryBandwidth] = None
        try:
            memory = await client.get_memory_bandwidth()
        except SeedrError as exc:
            log.debug("Seedr memory bandwidth fetch failed for %s: %s", self.user_id, _summarize_seedr_error(exc))

        summary = self._compose_account_summary(settings, memory)
        self._last_account_refresh = time.time()
        self._set_account_snapshot(summary, persist=persist, token=client.token if persist else None)
        return summary

    def _compose_account_summary(
        self,
        settings: models.UserSettings,
        memory: Optional[models.MemoryBandwidth],
    ) -> Dict[str, Any]:
        account_raw = settings.account.get_raw()
        summary: Dict[str, Any] = {
            "username": account_raw.get("username"),
            "user_id": account_raw.get("user_id"),
            "premium": account_raw.get("premium"),
            "space_used": account_raw.get("space_used"),
            "space_max": account_raw.get("space_max"),
            "bandwidth_used": account_raw.get("bandwidth_used"),
            "country": settings.country,
        }

        if memory is not None:
            summary.update(
                {
                    "space_used": memory.space_used,
                    "space_max": memory.space_max,
                    "bandwidth_used": memory.bandwidth_used,
                    "bandwidth_max": memory.bandwidth_max,
                    "premium": memory.is_premium,
                }
            )

        return summary

    def _update_account_from_contents(self, contents: models.ListContentsResult) -> None:
        if contents is None:
            return

        summary = dict(self._account_snapshot or {})
        changed = False

        if contents.space_used is not None and summary.get("space_used") != contents.space_used:
            summary["space_used"] = contents.space_used
            changed = True

        if contents.space_max is not None and contents.space_max != 0 and summary.get("space_max") != contents.space_max:
            summary["space_max"] = contents.space_max
            changed = True

        if changed:
            self._set_account_snapshot(summary, persist=False)

    # ------------------------------------------------------------------
    # Queue helpers
    # ------------------------------------------------------------------
    def get(self) -> Tuple[List[Tuple[str, DownloadInfo]], List[Tuple[str, DownloadInfo]]]:
        queue_items: List[Tuple[str, DownloadInfo]] = []
        for key, job in self.queue.items():
            info = job.info
            if getattr(info, "storage_key", None) is None:
                info.storage_key = key
            queue_items.append((key, info))
        for key, job in self.pending.items():
            info = job.info
            if getattr(info, "storage_key", None) is None:
                info.storage_key = key
            queue_items.append((key, info))

        done_items: List[Tuple[str, DownloadInfo]] = []
        for key, job in self.done.items():
            info = job.info
            if getattr(info, "storage_key", None) is None:
                info.storage_key = key
            done_items.append((key, info))
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
        display_title = title or self._infer_display_title(magnet_link, torrent_file)
        magnet_hash = add_hash_from_magnet(magnet_link) if magnet_link else None
        storage_key = build_download_storage_key('seedr', job_id, extra=magnet_hash)

        info = DownloadInfo(
            job_id,
            display_title,
            magnet_link or torrent_file or "",
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
            storage_key=storage_key,
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
        job.magnet_hash = magnet_hash
        self.pending[storage_key] = job

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
                if job.announced:
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

    async def clear_remote_storage(self) -> Dict[str, Any]:
        try:
            client = await self._ensure_client()
        except AuthenticationError:
            return {"status": "error", "msg": "Seedr account is not connected."}
        except SeedrError as exc:
            return {"status": "error", "msg": _format_seedr_error("Failed to connect to Seedr", exc)}

        removed = {"torrents": 0, "folders": 0, "files": 0}
        issues: List[str] = []

        async with self._semaphore:
            try:
                contents = await client.list_contents()
            except SeedrError as exc:
                return {"status": "error", "msg": _format_seedr_error("Unable to enumerate Seedr storage", exc)}

            for torrent in getattr(contents, "torrents", []) or []:
                try:
                    await client.delete_torrent(str(torrent.id))
                    removed["torrents"] += 1
                except SeedrError as exc:
                    issues.append(_format_seedr_error(f"Failed to delete torrent {getattr(torrent, 'name', torrent.id)}", exc))

            try:
                contents = await client.list_contents()
            except SeedrError:
                contents = None

            if contents is not None:
                for file in getattr(contents, "files", []) or []:
                    file_id = getattr(file, "folder_file_id", None) or getattr(file, "id", None)
                    if file_id is None:
                        continue
                    try:
                        await client.delete_file(str(file_id))
                        removed["files"] += 1
                    except SeedrError as exc:
                        issues.append(_format_seedr_error(f"Failed to delete file {getattr(file, 'name', file_id)}", exc))

                folders = _flatten_folders(getattr(contents, "folders", []) or [])
                for folder in reversed(folders):
                    folder_id = getattr(folder, "id", None)
                    if folder_id in (None, 0, -1):
                        continue
                    try:
                        await client.delete_folder(str(folder_id))
                        removed["folders"] += 1
                    except SeedrError as exc:
                        name = getattr(folder, "fullname", None) or getattr(folder, "name", None) or folder_id
                        issues.append(_format_seedr_error(f"Failed to delete folder {name}", exc))

            await self._refresh_account_snapshot(client, persist=True)

        status: Dict[str, Any] = {"status": "ok", "removed": removed}
        if issues:
            status.update({"status": "error", "msg": "Some Seedr items could not be removed.", "errors": issues})
        return status

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    async def _start_job(self, storage_key: str, job: SeedrJob) -> None:
        job.stage = "uploading"
        job.info.status = "pending"
        job.info.msg = "Preparing Seedr transfer"
        await self._notify_update(job)

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
            await self._finalize_error(storage_key, job, _format_seedr_error("Failed to connect to Seedr", exc))
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

        job.stage = "uploading"
        job.info.status = "pending"
        job.info.msg = "Adding torrent to Seedr"
        await self._notify_update(job)

        try:
            add_result = await client.add_torrent(folder_id=job.folder_id, **add_kwargs)
        except AuthenticationError as exc:
            self._invalidate_client()
            await self._finalize_error(storage_key, job, f"Seedr authentication failed: {exc}")
            return
        except SeedrError as exc:
            await self._finalize_error(storage_key, job, _format_seedr_error("Failed to add torrent", exc))
            return
        except Exception as exc:  # pragma: no cover
            await self._finalize_error(storage_key, job, f"Unexpected error adding torrent: {exc}")
            return

        self._cleanup_local_torrent(job)

        if not getattr(add_result, "result", True) or not getattr(add_result, "user_torrent_id", None):
            raw = add_result.get_raw() if hasattr(add_result, "get_raw") else None
            message = _summarize_seedr_add_failure(raw if isinstance(raw, dict) else None)
            await self._finalize_error(storage_key, job, message)
            return

        job.seedr_torrent_id = add_result.user_torrent_id
        job.expected_name = add_result.title or job.info.title
        job.seedr_folder_name = add_result.title or job.seedr_folder_name
        job.magnet_hash = add_result.torrent_hash or job.magnet_hash
        job.fetch_started_at = time.monotonic()
        job.last_progress_percent = None
        job.last_progress_at = job.fetch_started_at
        raw = add_result.get_raw() if hasattr(add_result, "get_raw") else None
        if isinstance(raw, dict):
            folder_id = raw.get("folder_id") or raw.get("folder") or raw.get("user_folder")
            if folder_id is not None:
                try:
                    job.seedr_folder_id = int(folder_id)
                except (TypeError, ValueError):
                    try:
                        job.seedr_folder_id = int(str(folder_id).strip())
                    except Exception:
                        pass
        job.stage = "waiting-seedr"
        job.info.status = "pending"
        job.info.msg = "Waiting for Seedr to fetch torrent"
        await self._notify_update(job)

        torrent_data = await self._monitor_torrent(client, storage_key, job)
        if not torrent_data:
            await self._cleanup_seedr(client, job)
            if job.canceled:
                self.queue.pop(storage_key, None)
                await self.notifier.canceled(storage_key)
            return

        torrent, contents = torrent_data
        job.seedr_folder_name = torrent.folder or torrent.name

        file_candidate = self._resolve_file(contents.files, torrent)
        success = False

        if file_candidate:
            success = await self._download_seedr_file(client, job, file_candidate)
        else:
            target_folder = self._resolve_folder(contents.folders, job.seedr_folder_name)
            if not target_folder:
                await self._finalize_error(storage_key, job, "Unable to locate Seedr folder for completed torrent.")
                await self._cleanup_seedr(client, job)
                return

            job.seedr_folder_id = target_folder.id

            try:
                folder_listing = await client.list_contents(str(target_folder.id))
            except SeedrError as exc:
                await self._finalize_error(storage_key, job, _format_seedr_error("Failed to list Seedr folder", exc))
                await self._cleanup_seedr(client, job)
                return

            nested_file = self._resolve_file(folder_listing.files, torrent)

            if nested_file and not folder_listing.folders:
                success = await self._download_seedr_file(client, job, nested_file)
            else:
                archive = await self._prepare_archive(client, storage_key, job, folder_listing)
                if not archive:
                    await self._cleanup_seedr(client, job)
                    return

                job.archive_url = archive.archive_url
                success = await self._download_archive(job, folder_listing, archive)

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
        error_streak = 0
        if not job.fetch_started_at:
            job.fetch_started_at = time.monotonic()
        if not job.last_progress_at:
            job.last_progress_at = job.fetch_started_at

        while not job.canceled:
            now = time.monotonic()
            if job.fetch_started_at and (now - job.fetch_started_at) > self.TORRENT_FETCH_TIMEOUT:
                await self._cleanup_seedr(client, job)
                await self._finalize_error(
                    storage_key,
                    job,
                    "Seedr did not finish fetching this torrent within the 3-hour limit enforced on free accounts.",
                )
                return None

            if (
                job.last_progress_percent is not None
                and job.last_progress_at
                and (now - job.last_progress_at) > self.TORRENT_STALL_TIMEOUT
            ):
                await self._cleanup_seedr(client, job)
                await self._finalize_error(
                    storage_key,
                    job,
                    "Seedr has not reported any download progress for an extended period. The job was canceled to avoid stalling the queue.",
                )
                return None

            try:
                contents = await client.list_contents()
                error_streak = 0
            except AuthenticationError as exc:
                self._invalidate_client()
                await self._finalize_error(storage_key, job, f"Seedr authentication failed: {exc}")
                return None
            except SeedrError as exc:
                error_streak += 1
                if error_streak >= self.MAX_STATUS_ERRORS:
                    await self._finalize_error(
                        storage_key,
                        job,
                        _format_seedr_error("Seedr status checks failed repeatedly", exc),
                    )
                    return None
                await asyncio.sleep(self.POLL_INTERVAL)
                log.debug("Seedr list_contents failed for %s: %s", self.user_id, _summarize_seedr_error(exc))
                continue

            self._update_account_from_contents(contents)

            if job.stage in {"waiting-seedr", "uploading", "queued"}:
                resolved_probe = self._detect_completed_without_torrent(contents, job)
                if resolved_probe:
                    job.last_progress_percent = 100.0
                    job.last_progress_at = time.monotonic()
                    job.stage = "ready"
                    job.info.msg = "Seedr finished fetching torrent"
                    await self._notify_update(job)
                    return resolved_probe

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
                resolved = await self._handle_missing_torrent(client, job, contents)
                if resolved:
                    job.last_progress_percent = 100.0
                    job.last_progress_at = time.monotonic()
                    job.stage = "ready"
                    job.info.msg = "Seedr finished fetching torrent"
                    await self._notify_update(job)
                    return resolved
                await asyncio.sleep(self.POLL_INTERVAL)
                continue

            progress = _progress_to_percent(torrent.progress)
            if progress is not None:
                job.info.percent = progress
                if job.last_progress_percent is None or progress > job.last_progress_percent:
                    job.last_progress_percent = progress
                    job.last_progress_at = time.monotonic()
            job.info.msg = f"Seedr progress: {torrent.progress}" if torrent.progress else "Seedr downloading"
            await self._notify_update(job)

            if progress is not None and progress >= 100:
                job.stage = "ready"
                job.info.msg = "Seedr finished fetching torrent"
                await self._notify_update(job)
                return torrent, contents

            await asyncio.sleep(self.POLL_INTERVAL)

        log.info("Seedr job %s canceled before completion", storage_key)
        job.stage = "canceled"
        job.info.status = "canceled"
        job.info.msg = "Seedr job canceled"
        await self._notify_update(job)
        return None

    async def _prepare_archive(
        self,
        client: AsyncSeedr,
        storage_key: str,
        job: SeedrJob,
        folder: models.Folder,
    ) -> Optional[models.CreateArchiveResult]:
        job.stage = "preparing-download"
        job.info.msg = "Preparing Seedr archive"
        await self._notify_update(job)
        attempt = 0
        while attempt < self.ARCHIVE_MAX_ATTEMPTS:
            attempt += 1
            try:
                archive = await client.create_archive(str(folder.id))
            except SeedrError as exc:
                log.error("Failed to create Seedr archive for folder %s: %s", folder.id, _summarize_seedr_error(exc))
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
            await self._finalize_error(getattr(job.info, "storage_key", job.info.url), job, "Download directory unavailable.")
            return False
        os.makedirs(directory, exist_ok=True)

        folder_name = folder.fullname or folder.name or job.info.title or f"seedr-{job.info.id}"
        filename = _sanitize_filename(folder_name)
        if not filename:
            filename = f"seedr-{job.info.id}"
        if not filename.lower().endswith('.zip'):
            filename = f"{filename}.zip"
        filename, path = _ensure_unique_path(directory, filename)

        await self._announce_job(job)
        job.stage = "downloading"
        job.info.status = "downloading"
        job.info.msg = "Downloading archive from Seedr"
        job.info.filename = filename
        job.info.title = filename
        job.info.percent = None
        job.info.speed = None
        job.info.eta = None
        await self._notify_update(job)

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
                            await self._notify_update(job)
        except asyncio.CancelledError:
            job.info.status = "canceled"
            job.info.msg = "Download canceled"
            await self._notify_update(job)
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
            return False
        except Exception as exc:
            await self._finalize_error(getattr(job.info, "storage_key", job.info.url), job, f"Failed to download archive: {exc}")
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
        job.stage = "complete"
        return True

    async def _download_seedr_file(self, client: AsyncSeedr, job: SeedrJob, file: models.File) -> bool:
        folder_id = getattr(file, "folder_id", None)
        if folder_id in (0, -1):
            job.seedr_folder_id = None
        elif folder_id is not None:
            job.seedr_folder_id = folder_id
        job.seedr_file_id = getattr(file, "folder_file_id", None)

        job.stage = "fetching-link"
        job.info.msg = "Requesting Seedr download link"
        await self._notify_update(job)
        try:
            fetch = await client.fetch_file(str(file.folder_file_id))
        except SeedrError as exc:
            await self._finalize_error(getattr(job.info, "storage_key", job.info.url), job, _format_seedr_error("Failed to fetch Seedr file", exc))
            return False

        if not fetch.result or not fetch.url:
            await self._finalize_error(getattr(job.info, "storage_key", job.info.url), job, "Seedr did not return a download link for the file.")
            return False

        directory = self.base_queue._resolve_download_directory(job.info)
        if not directory:
            await self._finalize_error(getattr(job.info, "storage_key", job.info.url), job, "Download directory unavailable.")
            return False
        os.makedirs(directory, exist_ok=True)

        base_name = fetch.name or file.name or job.info.title or f"seedr-{job.info.id}"
        filename = _sanitize_filename(base_name)
        if not filename:
            filename = f"seedr-{job.info.id}"
        filename, path = _ensure_unique_path(directory, filename)

        await self._announce_job(job)
        job.stage = "downloading"
        job.info.status = "downloading"
        job.info.msg = "Downloading from Seedr"
        job.info.filename = filename
        job.info.title = filename
        job.info.percent = 0.0
        job.info.speed = None
        job.info.eta = None
        job.info.size = file.size
        await self._notify_update(job)

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
                            await self._notify_update(job)
        except asyncio.CancelledError:
            job.info.status = "canceled"
            job.info.msg = "Download canceled"
            await self._notify_update(job)
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
            return False
        except Exception as exc:
            await self._finalize_error(getattr(job.info, "storage_key", job.info.url), job, f"Failed to download Seedr file: {exc}")
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
        job.stage = "complete"
        return True

    async def _cleanup_seedr(self, client: AsyncSeedr, job: SeedrJob) -> None:
        # Attempt to remove torrent and folder to free space
        if job.seedr_torrent_id is not None:
            with suppress_seedr_error():
                await client.delete_torrent(str(job.seedr_torrent_id))
        if job.seedr_file_id is not None:
            with suppress_seedr_error():
                await client.delete_file(str(job.seedr_file_id))
        if job.seedr_folder_id is not None and job.seedr_folder_id not in {0, -1}:
            with suppress_seedr_error():
                await client.delete_folder(str(job.seedr_folder_id))
        self._cleanup_local_torrent(job)
        job.seedr_file_id = None
        await self._refresh_account_snapshot(client, persist=True)

    async def _ensure_client(self) -> AsyncSeedr:
        async with self._client_lock:
            if self._client is not None:
                return self._client

            record = self.token_store.load_token()
            if not record:
                raise AuthenticationError("Seedr account not connected")

            self._set_account_snapshot(record.account or {}, persist=False)

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
        job.stage = "error"
        await self._notify_update(job)
        self.queue.pop(storage_key, None)
        self.done[storage_key] = job
        self._persist_completed()
        self._cleanup_local_torrent(job)

    def _detect_completed_without_torrent(
        self,
        contents: models.ListContentsResult,
        job: SeedrJob,
    ) -> Optional[Tuple[Any, models.ListContentsResult]]:
        name_candidates: List[str] = []
        if job.seedr_folder_name:
            name_candidates.append(job.seedr_folder_name)
        if job.expected_name:
            name_candidates.append(job.expected_name)
        seen = set()
        for name in name_candidates:
            if not name:
                continue
            normalized = name.strip().lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            folder = self._resolve_folder(contents.folders, name)
            if folder:
                job.seedr_folder_name = folder.fullname or folder.name
                job.seedr_folder_id = folder.id
                torrent_like = SimpleNamespace(
                    id=job.seedr_torrent_id or folder.id,
                    name=folder.name,
                    folder=folder.fullname or folder.name,
                    hash=job.magnet_hash or "",
                )
                return torrent_like, contents

        file_target = self._resolve_file(
            contents.files,
            SimpleNamespace(hash=job.magnet_hash or "", name=job.expected_name or job.seedr_folder_name or ""),
        )
        if file_target:
            if getattr(file_target, "folder_id", None) not in (None, 0, -1):
                job.seedr_folder_id = file_target.folder_id
            job.expected_name = file_target.name or job.expected_name
            torrent_like = SimpleNamespace(
                id=job.seedr_torrent_id or file_target.file_id,
                name=file_target.name,
                folder="",
                hash=file_target.hash or job.magnet_hash or "",
            )
            return torrent_like, contents
        return None

    async def _handle_missing_torrent(
        self,
        client: AsyncSeedr,
        job: SeedrJob,
        contents: models.ListContentsResult,
    ) -> Optional[Tuple[Any, models.ListContentsResult]]:
        resolved = self._detect_completed_without_torrent(contents, job)
        if resolved:
            return resolved

        folder_ids: List[int] = []

        if job.seedr_folder_id not in (None, 0, -1):
            try:
                folder_ids.append(int(job.seedr_folder_id))
            except (TypeError, ValueError):
                pass

        if job.seedr_folder_name:
            for folder in _flatten_folders(contents.folders):
                if folder.fullname and folder.fullname.strip().lower() == job.seedr_folder_name.strip().lower():
                    folder_ids.append(folder.id)
                elif folder.name.strip().lower() == job.seedr_folder_name.strip().lower():
                    folder_ids.append(folder.id)

        seen: Set[int] = set()
        for folder_id in folder_ids:
            if folder_id in seen:
                continue
            seen.add(folder_id)
            try:
                folder_listing = await client.list_contents(str(folder_id))
            except SeedrError as exc:
                log.debug("Seedr folder lookup failed for %s (folder %s): %s", self.user_id, folder_id, _summarize_seedr_error(exc))
                continue

            job.seedr_folder_id = folder_id
            job.seedr_folder_name = folder_listing.fullname or folder_listing.name
            self._update_account_from_contents(folder_listing)

            file_target = self._resolve_file(
                folder_listing.files,
                SimpleNamespace(hash=job.magnet_hash or "", name=job.expected_name or job.seedr_folder_name or ""),
            )
            if file_target:
                if getattr(file_target, "folder_file_id", None):
                    job.seedr_file_id = file_target.folder_file_id
                torrent_like = SimpleNamespace(
                    id=job.seedr_torrent_id or folder_id,
                    name=file_target.name or folder_listing.name,
                    folder=folder_listing.fullname or folder_listing.name,
                    hash=file_target.hash or job.magnet_hash or "",
                )
                return torrent_like, folder_listing

            if folder_listing.files or folder_listing.folders:
                torrent_like = SimpleNamespace(
                    id=job.seedr_torrent_id or folder_id,
                    name=folder_listing.name,
                    folder=folder_listing.fullname or folder_listing.name,
                    hash=job.magnet_hash or "",
                )
                return torrent_like, folder_listing

        return None

    def _resolve_folder(self, folders: List[models.Folder], target_name: Optional[str]) -> Optional[models.Folder]:
        if target_name is None:
            return None
        normalized = target_name.strip().lower()
        for folder in _flatten_folders(folders):
            name = folder.name.strip().lower()
            fullname = folder.fullname.strip().lower()
            if name == normalized or fullname == normalized:
                return folder
        return None

    def _resolve_file(
        self,
        files: List[models.File],
        torrent: models.Torrent,
    ) -> Optional[models.File]:
        if not files:
            return None
        if len(files) == 1:
            return files[0]
        target_hash = (torrent.hash or "").lower()
        if target_hash:
            for file in files:
                if file.hash and file.hash.lower() == target_hash:
                    return file
        sorted_files = sorted(files, key=lambda f: f.size, reverse=True)
        return sorted_files[0]

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
                storage_key = record.get("storage_key") or record.get("url")
                if not storage_key:
                    continue
                source_url = record.get("original_url") or record.get("url") or ""
                info = DownloadInfo(
                    record["id"],
                    record.get("title"),
                    source_url,
                    record.get("quality", "seedr"),
                    record.get("format", "seedr"),
                    record.get("folder", ""),
                    record.get("custom_name_prefix", ""),
                    error=record.get("error"),
                    entry=None,
                    playlist_item_limit=0,
                    cookiefile=None,
                    user_id=self.user_id,
                    original_url=record.get("original_url") or source_url,
                    provider="seedr",
                    storage_key=storage_key,
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
            job.stage = "complete" if info.status == "finished" else info.status or "completed"
            key = getattr(info, "storage_key", None) or storage_key
            info.storage_key = key
            self.done[key] = job

    def _persist_completed(self) -> None:
        self._enforce_history_limit()
        data = []
        for storage_key, job in self.done.items():
            info = job.info
            if getattr(info, "storage_key", None) is None:
                info.storage_key = storage_key
            data.append(
                {
                    "id": info.id,
                    "storage_key": storage_key,
                    "url": info.original_url or info.url,
                    "original_url": info.original_url or info.url,
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

    def snapshot(self) -> Dict[str, List[Dict[str, Any]]]:
        pending: List[Dict[str, Any]] = []
        in_progress: List[Dict[str, Any]] = []
        completed: List[Dict[str, Any]] = []
        failed: List[Dict[str, Any]] = []

        def add_entry(storage_key: str, job: SeedrJob, location: str) -> None:
            entry = {
                "id": storage_key,
                "title": job.info.title,
                "stage": job.stage,
                "status": job.info.status,
                "msg": job.info.msg,
                "percent": job.info.percent,
                "size": job.info.size,
                "created_at": job._added_at,
                "location": location,
                "provider": job.info.provider,
            }

            status = (job.info.status or "").lower()
            stage = job.stage

            if status == "error" or stage == "error":
                failed.append(entry)
                return

            if location == "completed" or stage in {"complete"} or status == "finished":
                completed.append(entry)
                return

            if location == "in_progress" or stage in {"waiting-seedr", "preparing-download", "fetching-link", "downloading"}:
                in_progress.append(entry)
                return

            pending.append(entry)

        for storage_key, job in self.pending.items():
            add_entry(storage_key, job, "pending")

        for storage_key, job in self.queue.items():
            add_entry(storage_key, job, "in_progress")

        for storage_key, job in self.done.items():
            add_entry(storage_key, job, "completed")

        completed.sort(key=lambda item: item.get("created_at") or 0, reverse=True)
        failed.sort(key=lambda item: item.get("created_at") or 0, reverse=True)

        return {
            "pending": pending,
            "in_progress": in_progress,
            "completed": completed[:20],
            "failed": failed[:20],
        }

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
            log.debug("Seedr cleanup error ignored: %s", _summarize_seedr_error(exc))
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

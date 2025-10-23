import asyncio
import json
import logging
import mimetypes
import os
import time
import uuid
from collections import OrderedDict
from typing import Dict, Optional, Tuple
from urllib.parse import unquote, urlparse

import aiohttp

from ytdl import DownloadInfo
class ProxySettingsStore:
    def __init__(self, path: str, default_enabled: bool, default_limit_mb: int):
        self.path = path
        self.limit_enabled = default_enabled
        self.limit_mb = default_limit_mb
        self._lock = asyncio.Lock()
        self._load()

    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, 'r', encoding='utf-8') as fp:
                data = json.load(fp)
            self.limit_enabled = bool(data.get('limit_enabled', self.limit_enabled))
            self.limit_mb = int(data.get('limit_mb', self.limit_mb))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            log.error(f'Failed to load proxy settings: {exc!r}')

    async def update(self, *, limit_enabled: Optional[bool] = None, limit_mb: Optional[int] = None):
        async with self._lock:
            if limit_enabled is not None:
                self.limit_enabled = limit_enabled
            if limit_mb is not None:
                self.limit_mb = max(limit_mb, 0)
            data = {'limit_enabled': self.limit_enabled, 'limit_mb': self.limit_mb}
            try:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                with open(self.path, 'w', encoding='utf-8') as fp:
                    json.dump(data, fp)
            except OSError as exc:
                log.error(f'Failed to persist proxy settings: {exc!r}')

    async def get(self) -> Dict[str, int]:
        async with self._lock:
            return {'limit_enabled': self.limit_enabled, 'limit_mb': self.limit_mb}

    @property
    def size_limit_bytes(self) -> Optional[int]:
        if not self.limit_enabled:
            return None
        return self.limit_mb * 1024 * 1024 if self.limit_mb > 0 else None


log = logging.getLogger('proxy')


def _sanitize_filename(candidate: str) -> str:
    candidate = candidate.replace('\0', '')
    name = candidate.strip().replace('\\', '/').split('/')[-1]
    return name or f'proxy-download-{uuid.uuid4().hex}'


def _guess_filename_from_headers(headers: aiohttp.typedefs.LooseHeaders, url: str) -> str:
    disposition = headers.get('Content-Disposition') if hasattr(headers, 'get') else None
    if disposition:
        parts = disposition.split(';')
        for part in parts:
            part = part.strip()
            if part.lower().startswith('filename='):
                filename = part.split('=', 1)[1].strip('"')
                if filename:
                    return _sanitize_filename(filename)
    parsed = urlparse(url)
    if parsed.path:
        filename = _sanitize_filename(unquote(parsed.path.split('/')[-1]))
        if filename:
            return filename
    return f'proxy-download-{uuid.uuid4().hex}'


def _ensure_unique_path(base_directory: str, filename: str) -> Tuple[str, str]:
    name, ext = os.path.splitext(filename)
    counter = 1
    candidate = filename
    while os.path.exists(os.path.join(base_directory, candidate)):
        candidate = f"{name}_{counter}{ext}"
        counter += 1
    return candidate, os.path.join(base_directory, candidate)


class ProxyDownloadJob:
    def __init__(self, info: DownloadInfo, source_url: str, size_limit: Optional[int] = None):
        self.info = info
        self.source_url = source_url
        self.size_limit = size_limit  # bytes or None
        self.content_type: Optional[str] = None
        self.total_bytes: Optional[int] = None
        self.downloaded_bytes: int = 0
        self.file_path: Optional[str] = None
        self._task: Optional[asyncio.Task] = None
        self._cancel_requested = False
        self._started_at: Optional[float] = None
        self._last_emit: float = 0.0

    def cancel(self):
        self._cancel_requested = True

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()


class ProxyDownloadManager:
    def __init__(self, config, notifier, base_queue, state_dir: str, user_id: str, settings_store: ProxySettingsStore, max_history_items: int = 200):
        self.config = config
        self.notifier = notifier
        self.base_queue = base_queue
        self.user_id = user_id
        self.settings_store = settings_store

        self.state_dir = os.path.join(state_dir, 'proxy')
        os.makedirs(self.state_dir, exist_ok=True)
        self.state_file = os.path.join(self.state_dir, 'completed.json')

        self.queue: 'OrderedDict[str, ProxyDownloadJob]' = OrderedDict()
        self.pending: 'OrderedDict[str, ProxyDownloadJob]' = OrderedDict()
        self.done: 'OrderedDict[str, ProxyDownloadJob]' = OrderedDict()
        self.max_history_items = max_history_items if max_history_items is not None else 200

        self._semaphore = None
        if self.config.DOWNLOAD_MODE == 'limited':
            try:
                limit = int(self.config.MAX_CONCURRENT_DOWNLOADS)
            except (TypeError, ValueError):
                limit = 1
            self._semaphore = asyncio.Semaphore(max(limit, 1))

        self._load_completed()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _load_completed(self):
        if not os.path.exists(self.state_file):
            return
        try:
            with open(self.state_file, 'r', encoding='utf-8') as fp:
                data = json.load(fp)
        except (OSError, json.JSONDecodeError) as exc:
            log.error(f'Failed to load proxy history for user {self.user_id}: {exc!r}')
            return

        for record in data:
            info = DownloadInfo(
                record['id'],
                record['title'],
                record['url'],
                record.get('quality', 'proxy'),
                record.get('format', 'proxy'),
                record.get('folder', ''),
                record.get('custom_name_prefix', ''),
                record.get('error'),
                entry=None,
                playlist_item_limit=0,
                cookiefile=None,
                user_id=self.user_id,
                original_url=record.get('original_url') or record['source_url'],
                provider='proxy'
            )
            info.filename = record.get('filename')
            info.size = record.get('size')
            info.status = record.get('status', 'finished')
            info.msg = record.get('msg')
            info.percent = 100.0
            info.speed = None
            info.eta = None
            info.timestamp = record.get('timestamp', time.time_ns())

            job = ProxyDownloadJob(info, record['source_url'])
            job.file_path = record.get('file_path')
            job.total_bytes = record.get('size')
            self.done[info.url] = job
        if self._enforce_history_limit():
            self._persist_completed()

    def _persist_completed(self):
        self._enforce_history_limit()
        data = []
        for job in self.done.values():
            info = job.info
            data.append({
                'id': info.id,
                'url': info.url,
                'source_url': job.source_url,
                'original_url': getattr(info, 'original_url', info.url),
                'title': info.title,
                'filename': info.filename,
                'folder': info.folder,
                'size': info.size,
                'status': info.status,
                'msg': info.msg,
                'timestamp': info.timestamp,
                'file_path': job.file_path,
                'quality': info.quality,
                'format': info.format,
                'custom_name_prefix': info.custom_name_prefix,
            })

        try:
            with open(self.state_file, 'w', encoding='utf-8') as fp:
                json.dump(data, fp)
        except OSError as exc:
            log.error(f'Failed to persist proxy history for user {self.user_id}: {exc!r}')

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

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------
    def get(self):
        queue_items = [(key, job.info) for key, job in self.queue.items()] + [
            (key, job.info) for key, job in self.pending.items()
        ]
        done_items = [(key, job.info) for key, job in self.done.items()]
        done_items.reverse()
        return queue_items, done_items

    def exists_in_done(self, download_id: str) -> bool:
        return download_id in self.done

    def get_done(self, download_id: str) -> Optional[ProxyDownloadJob]:
        return self.done.get(download_id)

    def resolve_file_path(self, info: DownloadInfo) -> Optional[str]:
        job = self.done.get(info.url)
        return job.file_path if job else None

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------
    async def probe(self, url: str) -> Dict:
        timeout = aiohttp.ClientTimeout(total=15)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.head(url, allow_redirects=True) as resp:
                    size = resp.headers.get('Content-Length')
                    disposition = resp.headers.get('Content-Disposition')
                    content_type = resp.headers.get('Content-Type')
                    filename = _guess_filename_from_headers(resp.headers, str(resp.url))
                    total_bytes = int(size) if size and size.isdigit() else None
                    size_limit_bytes = self.settings_store.size_limit_bytes
                    limit_exceeded = size_limit_bytes is not None and total_bytes and total_bytes > size_limit_bytes
                    return {
                        'status': 'ok',
                        'content_type': content_type,
                        'filename': filename,
                        'size': total_bytes,
                        'disposition': disposition,
                        'limit_exceeded': limit_exceeded,
                    }
        except Exception as exc:
            log.error(f'Proxy probe failed for {url}: {exc!r}')
            return {'status': 'error', 'msg': str(exc)}

    async def add_job(
        self,
        *,
        url: str,
        title: Optional[str],
        folder: str,
        custom_name_prefix: str = '',
        size_limit_override: Optional[int] = None,
        auto_start: bool = True,
        provider: str = 'proxy',
        quality_label: str = 'proxy',
        format_id: str = 'proxy',
        original_url: Optional[str] = None,
    ) -> Dict:
        display_title = title or _guess_filename_from_headers({}, url)
        job_id = uuid.uuid4().hex
        storage_key = f'proxy:{job_id}'

        info = DownloadInfo(
            job_id,
            display_title,
            storage_key,
            quality_label,
            format_id,
            folder or '',
            custom_name_prefix or '',
            error=None,
            entry=None,
            playlist_item_limit=0,
            cookiefile=None,
            user_id=self.user_id,
            original_url=original_url or url,
            provider=provider
        )

        info.status = 'pending'
        info.percent = 0.0
        info.speed = None
        info.eta = None

        effective_limit = size_limit_override if size_limit_override is not None else self.settings_store.size_limit_bytes
        job = ProxyDownloadJob(info, url, effective_limit)
        self.pending[storage_key] = job
        await self.notifier.added(info)

        if auto_start:
            await self.start_jobs([storage_key])
        return {'status': 'ok', 'id': storage_key}

    async def start_jobs(self, ids):
        for storage_key in ids:
            job = self.pending.pop(storage_key, None)
            if not job:
                continue
            self.queue[storage_key] = job
            await self._start_download(job)
        return {'status': 'ok'}

    async def cancel(self, ids):
        for download_id in ids:
            if download_id in self.pending:
                job = self.pending.pop(download_id)
                job.info.status = 'canceled'
                await self.notifier.canceled(download_id)
                continue
            if download_id in self.queue:
                job = self.queue[download_id]
                job.cancel()
        return {'status': 'ok'}

    async def clear(self, ids):
        missing_files = []
        deleted = []
        errors = {}

        for download_id in ids:
            job = self.done.get(download_id)
            if not job:
                continue

            file_path = job.file_path
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    deleted.append(job.info.filename or job.info.title)
                except OSError as exc:
                    errors[download_id] = str(exc)
                    continue
            else:
                missing_files.append(job.info.filename or job.info.title)

            self.done.pop(download_id, None)
            await self.notifier.cleared(download_id)

        self._persist_completed()

        result = {'status': 'ok', 'deleted': deleted, 'missing': missing_files}
        if errors:
            result.update({'status': 'error', 'errors': errors, 'msg': 'Some files could not be removed from disk.'})
        return result

    async def rename(self, download_id: str, new_name: str):
        job = self.done.get(download_id)
        if not job:
            return {'status': 'error', 'msg': 'Download not found.'}

        if not job.file_path or not os.path.exists(job.file_path):
            return {'status': 'error', 'msg': 'Original file no longer exists.'}

        directory = os.path.dirname(job.file_path)
        sanitized = _sanitize_filename(new_name)
        target_path = os.path.join(directory, sanitized)

        if os.path.exists(target_path):
            return {'status': 'error', 'msg': 'A file with the requested name already exists.'}

        try:
            os.rename(job.file_path, target_path)
        except OSError as exc:
            return {'status': 'error', 'msg': f'Failed to rename file: {exc}'}

        job.file_path = target_path
        job.info.filename = sanitized
        try:
            job.info.size = os.path.getsize(target_path)
        except OSError:
            pass

        await self.notifier.renamed(job.info)
        self._persist_completed()
        return {'status': 'ok', 'filename': sanitized, 'title': sanitized}

    # ------------------------------------------------------------------
    # Internal download logic
    # ------------------------------------------------------------------
    async def _start_download(self, job: ProxyDownloadJob):
        job.info.status = 'preparing'
        await self.notifier.updated(job.info)

        if self._semaphore is not None:
            job._task = asyncio.create_task(self._run_with_semaphore(job))
        else:
            job._task = asyncio.create_task(self._run_download(job))

    async def _run_with_semaphore(self, job: ProxyDownloadJob):
        async with self._semaphore:
            await self._run_download(job)

    async def _run_download(self, job: ProxyDownloadJob):
        storage_key = job.info.url
        directory = self.base_queue._resolve_download_directory(job.info)  # reuse base logic
        if not directory:
            job.info.status = 'error'
            job.info.msg = 'Download directory unavailable.'
            await self.notifier.updated(job.info)
            self.queue.pop(storage_key, None)
            return

        os.makedirs(directory, exist_ok=True)

        timeout = aiohttp.ClientTimeout(total=None)
        job._started_at = time.monotonic()
        job.info.status = 'downloading'
        await self.notifier.updated(job.info)

        chunk_size = 256 * 1024

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(job.source_url, allow_redirects=True) as resp:
                    if resp.status >= 400:
                        raise aiohttp.ClientResponseError(resp.request_info, resp.history, status=resp.status, message=resp.reason)

                    job.content_type = resp.headers.get('Content-Type')
                    size_header = resp.headers.get('Content-Length')
                    if size_header and size_header.isdigit():
                        job.total_bytes = int(size_header)
                    else:
                        job.total_bytes = None

                    if job.size_limit is not None and job.total_bytes and job.total_bytes > job.size_limit:
                        raise ValueError('File exceeds configured size limit')

                    filename = _guess_filename_from_headers(resp.headers, str(resp.url))
                    original_extension = os.path.splitext(urlparse(job.source_url).path)[1]

                    def _replace_extension(name: str, new_ext: Optional[str]) -> str:
                        base, _ = os.path.splitext(name)
                        return f"{base}{new_ext}" if new_ext else name

                    invalid_exts = {'', '.unknown_video', '.unknown_audio', '.unknown'}
                    current_ext = os.path.splitext(filename)[1].lower()

                    if current_ext in invalid_exts and original_extension:
                        filename = _replace_extension(filename, original_extension)
                        current_ext = os.path.splitext(filename)[1].lower()

                    if (current_ext in invalid_exts) and job.content_type:
                        guess = mimetypes.guess_extension(job.content_type.split(';')[0])
                        if guess:
                            filename = _replace_extension(filename, guess)
                            current_ext = os.path.splitext(filename)[1].lower()

                    if current_ext in invalid_exts:
                        filename = _sanitize_filename(filename)
                        if original_extension:
                            filename = _replace_extension(filename, original_extension)

                    filename, file_path = _ensure_unique_path(directory, filename)
                    job.file_path = file_path
                    job.info.filename = filename

                    with open(file_path, 'wb') as fh:
                        async for chunk in resp.content.iter_chunked(chunk_size):
                            if job._cancel_requested:
                                raise asyncio.CancelledError()
                            if not chunk:
                                continue
                            fh.write(chunk)
                            job.downloaded_bytes += len(chunk)
                            self._update_progress(job)
                            await self.notifier.updated(job.info)

        except asyncio.CancelledError:
            job.info.status = 'canceled'
            job.info.msg = 'Download canceled'
            if job.file_path and os.path.exists(job.file_path):
                try:
                    os.remove(job.file_path)
                except OSError:
                    pass
            await self.notifier.updated(job.info)
            await self.notifier.canceled(storage_key)
            self.queue.pop(storage_key, None)
            job._task = None
            return
        except Exception as exc:
            log.error(f'Proxy download failed for {job.source_url}: {exc!r}')
            job.info.status = 'error'
            job.info.msg = str(exc)
            if job.file_path and os.path.exists(job.file_path):
                try:
                    os.remove(job.file_path)
                except OSError:
                    pass
            await self.notifier.updated(job.info)
            self.queue.pop(storage_key, None)
            job._task = None
            return

        job.info.status = 'finished'
        job.info.msg = None
        job.info.percent = 100.0
        try:
            job.info.size = os.path.getsize(job.file_path) if job.file_path else job.total_bytes
        except OSError:
            job.info.size = job.total_bytes

        self.queue.pop(storage_key, None)
        self.done[storage_key] = job
        await self.notifier.completed(job.info)
        self._persist_completed()
        job._task = None

    def _update_progress(self, job: ProxyDownloadJob):
        now = time.monotonic()
        if job._started_at is None:
            job._started_at = now

        elapsed = max(now - job._started_at, 1e-6)
        speed = job.downloaded_bytes / elapsed
        job.info.speed = speed

        if job.total_bytes:
            job.info.percent = (job.downloaded_bytes / job.total_bytes) * 100
            remaining = max(job.total_bytes - job.downloaded_bytes, 0)
            job.info.eta = int(remaining / speed) if speed > 0 else None
        else:
            job.info.percent = None
            job.info.eta = None

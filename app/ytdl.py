import os
import yt_dlp
from collections import OrderedDict
import shelve
import time
import asyncio
import multiprocessing
import logging
import math
import re

import yt_dlp.networking.impersonate
from dl_formats import get_format, get_opts, AUDIO_FORMATS
from datetime import datetime
from typing import Optional, Any

log = logging.getLogger('ytdl')

COOKIE_WARNING_MARKERS = (
    'cookies are no longer valid',
    "sign in to confirm you're not a bot",
    "sign in to confirm you’re not a bot",
    'use --cookies',
    'cookies for the authentication',
    'please sign in',
)

class DownloadQueueNotifier:
    async def added(self, dl):
        raise NotImplementedError

    async def updated(self, dl):
        raise NotImplementedError

    async def completed(self, dl):
        raise NotImplementedError

    async def canceled(self, id):
        raise NotImplementedError

    async def cleared(self, id):
        raise NotImplementedError

    async def renamed(self, dl):
        raise NotImplementedError

class DownloadInfo:
    def __init__(self, id, title, url, quality, format, folder, custom_name_prefix, error, entry, playlist_item_limit, cookiefile=None, user_id=None, original_url=None, provider='ytdlp', cookie_profile_id=None):
        self.id = id if len(custom_name_prefix) == 0 else f'{custom_name_prefix}.{id}'
        self.title = title if len(custom_name_prefix) == 0 else f'{custom_name_prefix}.{title}'
        self.url = url
        self.original_url = original_url or url
        self.quality = quality
        self.format = format
        self.folder = folder
        self.custom_name_prefix = custom_name_prefix
        self.filename = None
        self.msg = self.percent = self.speed = self.eta = None
        self.status = "pending"
        self.size = None
        self.timestamp = time.time_ns()
        self.error = error
        self.entry = entry
        self.playlist_item_limit = playlist_item_limit
        self.cookiefile = cookiefile
        self.cookie_profile_id = cookie_profile_id
        self.user_id = user_id
        self.provider = provider
        self.cookie_warning = None
        self.cookie_warning_at = None

class Download:
    manager = None

    def __init__(
        self,
        download_dir,
        temp_dir,
        output_template,
        output_template_chapter,
        quality,
        format,
        ytdl_opts,
        info,
        size_limit_bytes: Optional[int] = None,
    ):
        self.download_dir = download_dir
        self.temp_dir = temp_dir
        self.output_template = output_template
        self.output_template_chapter = output_template_chapter
        self.format = get_format(format, quality)
        self.ytdl_opts = get_opts(format, quality, ytdl_opts)
        if "impersonate" in self.ytdl_opts:
            self.ytdl_opts["impersonate"] = yt_dlp.networking.impersonate.ImpersonateTarget.from_str(self.ytdl_opts["impersonate"])
        self.info = info
        self.canceled = False
        self.tmpfilename = None
        self.status_queue = None
        self.proc = None
        self.loop = None
        self.notifier = None
        self.size_limit_bytes = size_limit_bytes
        self._limit_error_emitted = False

    def _download(self):
        log.info(f"Starting download for: {self.info.title} ({self.info.url})")
        try:
            def put_status(st):
                self.status_queue.put({k: v for k, v in st.items() if k in (
                    'tmpfilename',
                    'filename',
                    'status',
                    'msg',
                    'total_bytes',
                    'total_bytes_estimate',
                    'downloaded_bytes',
                    'speed',
                    'eta',
                )})

            def put_status_postprocessor(d):
                if d['postprocessor'] == 'MoveFiles' and d['status'] == 'finished':
                    if '__finaldir' in d['info_dict']:
                        filename = os.path.join(d['info_dict']['__finaldir'], os.path.basename(d['info_dict']['filepath']))
                    else:
                        filename = d['info_dict']['filepath']
                    self.status_queue.put({'status': 'finished', 'filename': filename})

            status_queue = self.status_queue

            class QueueLogger:
                def debug(self, msg):
                    log.debug(msg)

                def info(self, msg):
                    log.info(msg)

                def warning(self, msg):
                    log.warning(msg)
                    text = str(msg)
                    lowered = text.lower()
                    if any(marker in lowered for marker in COOKIE_WARNING_MARKERS):
                        status_queue.put({'__event': 'cookie_warning', 'message': text})

                def error(self, msg):
                    log.error(msg)

            ret = yt_dlp.YoutubeDL(params={
                'quiet': True,
                'no_color': True,
                'paths': {"home": self.download_dir, "temp": self.temp_dir},
                'outtmpl': { "default": self.output_template, "chapter": self.output_template_chapter },
                'format': self.format,
                'socket_timeout': 30,
                'ignore_no_formats_error': True,
                'progress_hooks': [put_status],
                'postprocessor_hooks': [put_status_postprocessor],
                'logger': QueueLogger(),
                **self.ytdl_opts,
            }).download([self.info.url])
            self.status_queue.put({'status': 'finished' if ret == 0 else 'error'})
            log.info(f"Finished download for: {self.info.title}")
        except yt_dlp.utils.YoutubeDLError as exc:
            log.error(f"Download error for {self.info.title}: {str(exc)}")
            self.status_queue.put({'status': 'error', 'msg': str(exc), '__event': 'download_error'})

    def _calculate_limit_violation(self, status: Any) -> Optional[int]:
        limit = self.size_limit_bytes
        if not limit or not isinstance(status, dict):
            return None
        total = status.get('total_bytes') or status.get('total_bytes_estimate')
        downloaded = status.get('downloaded_bytes')
        if isinstance(total, (int, float)) and total > limit:
            return int(total)
        if isinstance(downloaded, (int, float)) and downloaded > limit:
            return int(downloaded)
        return None

    def _format_limit_message(self, approx_bytes: int) -> str:
        limit = self.size_limit_bytes or 0
        limit_mb = max(1, math.ceil(limit / (1024 * 1024))) if limit else 0
        approx_mb = max(1, math.ceil(approx_bytes / (1024 * 1024)))
        if limit_mb > 0:
            return (
                f'This download requires approximately {approx_mb} MB which exceeds '
                f'the configured size limit of {limit_mb} MB.'
            )
        return (
            f'This download requires approximately {approx_mb} MB and cannot be processed '
            'due to the configured size limit.'
        )

    async def _abort_for_limit(self, approx_bytes: int):
        if self._limit_error_emitted:
            return
        self._limit_error_emitted = True
        message = self._format_limit_message(approx_bytes)
        self.info.status = 'error'
        self.info.msg = message
        self.info.error = message
        self.info.percent = 0
        try:
            if self.proc and self.proc.is_alive():
                self.proc.kill()
        except Exception as exc:
            log.debug('Failed to kill process for size limit enforcement: %s', exc)
        if self.status_queue is not None:
            try:
                self.status_queue.put(None)
            except Exception:
                pass
        await self.notifier.updated(self.info)

    async def start(self, notifier):
        log.info(f"Preparing download for: {self.info.title}")
        if Download.manager is None:
            Download.manager = multiprocessing.Manager()
        self.status_queue = Download.manager.Queue()
        self.proc = multiprocessing.Process(target=self._download)
        self.proc.start()
        self.loop = asyncio.get_running_loop()
        self.notifier = notifier
        self.info.status = 'preparing'
        await self.notifier.updated(self.info)
        asyncio.create_task(self.update_status())
        return await self.loop.run_in_executor(None, self.proc.join)

    def cancel(self):
        log.info(f"Cancelling download: {self.info.title}")
        if self.running():
            try:
                self.proc.kill()
            except Exception as e:
                log.error(f"Error killing process for {self.info.title}: {e}")
        self.canceled = True
        if self.status_queue is not None:
            self.status_queue.put(None)

    def close(self):
        log.info(f"Closing download process for: {self.info.title}")
        if self.started():
            self.proc.close()
            if self.status_queue is not None:
                self.status_queue.put(None)

    def running(self):
        try:
            return self.proc is not None and self.proc.is_alive()
        except ValueError:
            return False

    def started(self):
        return self.proc is not None

    async def update_status(self):
        while True:
            status = await self.loop.run_in_executor(None, self.status_queue.get)
            if status is None:
                log.info(f"Status update finished for: {self.info.title}")
                return
            event = status.get('__event') if isinstance(status, dict) else None
            if event == 'cookie_warning':
                self.info.cookie_warning = status.get('message')
                self.info.cookie_warning_at = time.time()
                continue
            if isinstance(status, dict):
                violation_bytes = self._calculate_limit_violation(status)
                if violation_bytes is not None:
                    await self._abort_for_limit(violation_bytes)
                    return
            if self.canceled:
                log.info(f"Download {self.info.title} is canceled; stopping status updates.")
                return
            self.tmpfilename = status.get('tmpfilename')
            if 'filename' in status:
                fileName = status.get('filename')
                self.info.filename = os.path.relpath(fileName, self.download_dir)
                self.info.size = os.path.getsize(fileName) if os.path.exists(fileName) else None
                if self.info.format == 'thumbnail':
                    self.info.filename = re.sub(r'\.webm$', '.jpg', self.info.filename)
            self.info.status = status['status']
            self.info.msg = status.get('msg')
            if 'downloaded_bytes' in status:
                total = status.get('total_bytes') or status.get('total_bytes_estimate')
                if total:
                    self.info.percent = status['downloaded_bytes'] / total * 100
            self.info.speed = status.get('speed')
            self.info.eta = status.get('eta')
            log.info(f"Updating status for {self.info.title}: {status}")
            await self.notifier.updated(self.info)

class PersistentQueue:
    def __init__(self, path):
        pdir = os.path.dirname(path)
        if not os.path.isdir(pdir):
            os.mkdir(pdir)
        with shelve.open(path, 'c'):
            pass
        self.path = path
        self.dict = OrderedDict()

    def load(self):
        for k, v in self.saved_items():
            self.dict[k] = Download(None, None, None, None, None, None, {}, v)

    def exists(self, key):
        return key in self.dict

    def get(self, key):
        return self.dict[key]

    def items(self):
        return self.dict.items()

    def saved_items(self):
        with shelve.open(self.path, 'r') as shelf:
            return sorted(shelf.items(), key=lambda item: item[1].timestamp)

    def put(self, value):
        key = value.info.url
        self.dict[key] = value
        with shelve.open(self.path, 'w') as shelf:
            shelf[key] = value.info

    def delete(self, key):
        if key in self.dict:
            del self.dict[key]
            with shelve.open(self.path, 'w') as shelf:
                shelf.pop(key, None)

    def next(self):
        k, v = next(iter(self.dict.items()))
        return k, v

    def empty(self):
        return not bool(self.dict)

    def truncate(self, max_items: int):
        if max_items is None:
            return
        if max_items <= 0:
            if self.dict:
                self.dict.clear()
                with shelve.open(self.path, 'n'):
                    pass
            return
        if len(self.dict) <= max_items:
            return
        removed_keys = []
        while len(self.dict) > max_items:
            key, _ = self.dict.popitem(last=False)
            removed_keys.append(key)
        if removed_keys:
            with shelve.open(self.path, 'w') as shelf:
                for key in removed_keys:
                    shelf.pop(key, None)

class DownloadQueue:
    def __init__(
        self,
        config,
        notifier,
        state_dir=None,
        user_id=None,
        cookie_status_store=None,
        download_limit_source=None,
        max_history_items: int = 200,
    ):
        self.config = config
        self.notifier = notifier
        self.user_id = user_id
        self.state_dir = state_dir or self.config.STATE_DIR
        os.makedirs(self.state_dir, exist_ok=True)
        self.queue = PersistentQueue(os.path.join(self.state_dir, 'queue'))
        self.done = PersistentQueue(os.path.join(self.state_dir, 'completed'))
        self.pending = PersistentQueue(os.path.join(self.state_dir, 'pending'))
        self.active_downloads = set()
        self.semaphore = None
        self.cookie_status_store = cookie_status_store
        self.download_limit_source = download_limit_source
        self.max_history_items = max_history_items if max_history_items is not None else 200
        # For sequential mode, use an asyncio lock to ensure one-at-a-time execution.
        if self.config.DOWNLOAD_MODE == 'sequential':
            self.seq_lock = asyncio.Lock()
        elif self.config.DOWNLOAD_MODE == 'limited':
            self.semaphore = asyncio.Semaphore(int(self.config.MAX_CONCURRENT_DOWNLOADS))
        
        self.done.load()
        if self.max_history_items >= 0:
            self.done.truncate(self.max_history_items)

    async def __import_queue(self):
        for k, v in self.queue.saved_items():
            cookie_path = getattr(v, 'cookiefile', None)
            await self.__add_download(v, True, cookie_path)

    async def __import_pending(self):
        for k, v in self.pending.saved_items():
            cookie_path = getattr(v, 'cookiefile', None)
            await self.__add_download(v, False, cookie_path)

    async def initialize(self):
        log.info("Initializing DownloadQueue")
        asyncio.create_task(self.__import_queue())
        asyncio.create_task(self.__import_pending())

    def _current_size_limit(self) -> Optional[int]:
        if not self.download_limit_source:
            return None
        try:
            limit = getattr(self.download_limit_source, 'size_limit_bytes', None)
            if callable(limit):
                limit = limit()
        except Exception as exc:
            log.debug('Failed to resolve size limit: %s', exc)
            return None
        if not isinstance(limit, (int, float)):
            return None
        limit_int = int(limit)
        if limit_int <= 0:
            return None
        return limit_int

    def _apply_size_limit(self, download: Download):
        limit = self._current_size_limit()
        download.size_limit_bytes = limit

    def _estimate_download_size(self, info: DownloadInfo) -> Optional[int]:
        entry = getattr(info, 'entry', None)
        if not isinstance(entry, dict):
            return None
        for key in ('filesize', 'filesize_approx', 'filesize_estimate', 'filesize_approximation'):
            value = entry.get(key)
            if isinstance(value, (int, float)) and value > 0:
                return int(value)

        def _accumulate(items: Any) -> Optional[int]:
            if not isinstance(items, list):
                return None
            total = 0
            found = False
            for item in items:
                if not isinstance(item, dict):
                    continue
                size = item.get('filesize') or item.get('filesize_approx') or item.get('filesize_estimate')
                if isinstance(size, (int, float)) and size > 0:
                    total += int(size)
                    found = True
            return total if found else None

        requested_downloads = _accumulate(entry.get('requested_downloads'))
        if requested_downloads is not None:
            return requested_downloads

        requested_formats = _accumulate(entry.get('requested_formats'))
        if requested_formats is not None:
            return requested_formats

        fragments = entry.get('fragments')
        if isinstance(fragments, list):
            total = 0
            found = False
            for fragment in fragments:
                if not isinstance(fragment, dict):
                    continue
                size = fragment.get('filesize') or fragment.get('filesize_approx')
                if isinstance(size, (int, float)) and size > 0:
                    total += int(size)
                    found = True
            if found:
                return total
        return None

    def _format_limit_error(self, estimated_bytes: int, limit_bytes: int) -> str:
        estimated_mb = max(1, math.ceil(estimated_bytes / (1024 * 1024)))
        limit_mb = max(1, math.ceil(limit_bytes / (1024 * 1024)))
        return (
            f'This download is estimated at {estimated_mb} MB which exceeds the configured '
            f'size limit of {limit_mb} MB.'
        )

    def _resolve_download_directory(self, info):
        base_directory = self.config.DOWNLOAD_DIR if (info.quality != 'audio' and info.format not in AUDIO_FORMATS) else self.config.AUDIO_DOWNLOAD_DIR
        base_directory = os.path.realpath(base_directory)
        if info.folder:
            dldirectory = os.path.realpath(os.path.join(base_directory, info.folder))
            if not dldirectory.startswith(base_directory):
                log.warning(f'Folder "{info.folder}" for download {info.url} resolved outside the base directory; skipping file removal.')
                return None
            return dldirectory
        return base_directory

    async def __start_download(self, download):
        if download.canceled:
            log.info(f"Download {download.info.title} was canceled, skipping start.")
            return
        self._apply_size_limit(download)
        if self.config.DOWNLOAD_MODE == 'sequential':
            async with self.seq_lock:
                log.info("Starting sequential download.")
                await download.start(self.notifier)
                self._post_download_cleanup(download)
        elif self.config.DOWNLOAD_MODE == 'limited' and self.semaphore is not None:
            await self.__limited_concurrent_download(download)
        else:
            await self.__concurrent_download(download)

    async def __concurrent_download(self, download):
        log.info("Starting concurrent download without limits.")
        asyncio.create_task(self._run_download(download))

    async def __limited_concurrent_download(self, download):
        log.info("Starting limited concurrent download.")
        async with self.semaphore:
            await self._run_download(download)

    async def _run_download(self, download):
        if download.canceled:
            log.info(f"Download {download.info.title} is canceled; skipping start.")
            return
        await download.start(self.notifier)
        self._post_download_cleanup(download)

    def _is_cookie_error(self, message):
        if not message:
            return False
        lowered = str(message).lower()
        return any(marker in lowered for marker in COOKIE_WARNING_MARKERS)

    def _post_download_cleanup(self, download):
        if download.info.status != 'finished':
            if download.tmpfilename and os.path.isfile(download.tmpfilename):
                try:
                    os.remove(download.tmpfilename)
                except:
                    pass
            download.info.status = 'error'
        download.close()
        if (
            self.cookie_status_store
            and download.info.cookiefile
            and download.info.user_id
        ):
            if download.info.status == 'finished':
                self.cookie_status_store.mark_valid(download.info.user_id)
            else:
                message = download.info.cookie_warning or download.info.msg
                if download.info.cookie_warning or self._is_cookie_error(message):
                    self.cookie_status_store.mark_invalid(download.info.user_id, message)
        if self.queue.exists(download.info.url):
            self.queue.delete(download.info.url)
            if download.canceled:
                asyncio.create_task(self.notifier.canceled(download.info.url))
            else:
                self.done.put(download)
                if self.max_history_items >= 0:
                    self.done.truncate(self.max_history_items)
                asyncio.create_task(self.notifier.completed(download.info))

    def __extract_info(self, url, playlist_strict_mode, cookie_path=None):
        params = {
            'quiet': True,
            'no_color': True,
            'extract_flat': True,
            'ignore_no_formats_error': True,
            'noplaylist': playlist_strict_mode,
            'paths': {"home": self.config.DOWNLOAD_DIR, "temp": self.config.TEMP_DIR},
            **self.config.YTDL_OPTIONS,
        }
        if 'impersonate' in self.config.YTDL_OPTIONS:
            params['impersonate'] = yt_dlp.networking.impersonate.ImpersonateTarget.from_str(self.config.YTDL_OPTIONS['impersonate'])
        if cookie_path:
            params['cookiefile'] = cookie_path
            log.info('yt-dlp metadata extraction using cookie file %s', cookie_path)
        return yt_dlp.YoutubeDL(params=params).extract_info(url, download=False)

    def __calc_download_path(self, quality, format, folder):
        base_directory = self.config.DOWNLOAD_DIR if (quality != 'audio' and format not in AUDIO_FORMATS) else self.config.AUDIO_DOWNLOAD_DIR
        if folder:
            if not self.config.CUSTOM_DIRS:
                return None, {'status': 'error', 'msg': f'A folder for the download was specified but CUSTOM_DIRS is not true in the configuration.'}
            dldirectory = os.path.realpath(os.path.join(base_directory, folder))
            real_base_directory = os.path.realpath(base_directory)
            if not dldirectory.startswith(real_base_directory):
                return None, {'status': 'error', 'msg': f'Folder "{folder}" must resolve inside the base download directory "{real_base_directory}"'}
            if not os.path.isdir(dldirectory):
                if not self.config.CREATE_CUSTOM_DIRS:
                    return None, {'status': 'error', 'msg': f'Folder "{folder}" for download does not exist inside base directory "{real_base_directory}", and CREATE_CUSTOM_DIRS is not true in the configuration.'}
                os.makedirs(dldirectory, exist_ok=True)
        else:
            dldirectory = base_directory
        return dldirectory, None

    async def __add_download(self, dl, auto_start, cookie_path=None):
        dldirectory, error_message = self.__calc_download_path(dl.quality, dl.format, dl.folder)
        if error_message is not None:
            return error_message
        output = self.config.OUTPUT_TEMPLATE if len(dl.custom_name_prefix) == 0 else f'{dl.custom_name_prefix}.{self.config.OUTPUT_TEMPLATE}'
        output_chapter = self.config.OUTPUT_TEMPLATE_CHAPTER
        entry = getattr(dl, 'entry', None)
        if entry is not None and 'playlist' in entry and entry['playlist'] is not None:
            if len(self.config.OUTPUT_TEMPLATE_PLAYLIST):
                output = self.config.OUTPUT_TEMPLATE_PLAYLIST
            for property, value in entry.items():
                if property.startswith("playlist"):
                    output = output.replace(f"%({property})s", str(value))
        ytdl_options = dict(self.config.YTDL_OPTIONS)
        playlist_item_limit = getattr(dl, 'playlist_item_limit', 0)
        if playlist_item_limit > 0:
            log.info(f'playlist limit is set. Processing only first {playlist_item_limit} entries')
            ytdl_options['playlistend'] = playlist_item_limit
        if cookie_path:
            ytdl_options['cookiefile'] = cookie_path
            dl.cookiefile = cookie_path
            try:
                size = os.path.getsize(cookie_path)
            except OSError:
                size = -1
            log.info('yt-dlp download %s will use cookie file %s (size=%s)', dl.id, cookie_path, size)
        size_limit = self._current_size_limit()
        estimated_size = self._estimate_download_size(dl)
        if size_limit is not None and estimated_size is not None and estimated_size > size_limit:
            msg = self._format_limit_error(estimated_size, size_limit)
            log.info('Download %s rejected due to size limit (%s bytes > %s bytes)', dl.id, estimated_size, size_limit)
            return {'status': 'error', 'msg': msg}
        download = Download(
            dldirectory,
            self.config.TEMP_DIR,
            output,
            output_chapter,
            dl.quality,
            dl.format,
            ytdl_options,
            dl,
            size_limit_bytes=size_limit,
        )
        self._apply_size_limit(download)
        if auto_start is True:
            self.queue.put(download)
            asyncio.create_task(self.__start_download(download))
        else:
            self.pending.put(download)
        await self.notifier.added(dl)
        return {'status': 'ok'}

    async def __add_entry(self, entry, quality, format, folder, custom_name_prefix, playlist_strict_mode, playlist_item_limit, auto_start, already, cookie_path=None, cookie_profile_id=None):
        if not entry:
            return {'status': 'error', 'msg': "Invalid/empty data was given."}

        error = None
        if "live_status" in entry and "release_timestamp" in entry and entry.get("live_status") == "is_upcoming":
            dt_ts = datetime.fromtimestamp(entry.get("release_timestamp")).strftime('%Y-%m-%d %H:%M:%S %z')
            error = f"Live stream is scheduled to start at {dt_ts}"
        else:
            if "msg" in entry:
                error = entry["msg"]

        etype = entry.get('_type') or 'video'

        if etype.startswith('url'):
            log.debug('Processing as an url')
            return await self.add(entry['url'], quality, format, folder, custom_name_prefix, playlist_strict_mode, playlist_item_limit, auto_start, already, cookie_path, cookie_profile_id)
        elif etype == 'playlist':
            log.debug('Processing as a playlist')
            entries = entry['entries']
            log.info(f'playlist detected with {len(entries)} entries')
            playlist_index_digits = len(str(len(entries)))
            results = []
            if playlist_item_limit > 0:
                log.info(f'Playlist item limit is set. Processing only first {playlist_item_limit} entries')
                entries = entries[:playlist_item_limit]
            for index, etr in enumerate(entries, start=1):
                etr["_type"] = "video"
                etr["playlist"] = entry["id"]
                etr["playlist_index"] = '{{0:0{0:d}d}}'.format(playlist_index_digits).format(index)
                for property in ("id", "title", "uploader", "uploader_id"):
                    if property in entry:
                        etr[f"playlist_{property}"] = entry[property]
                results.append(await self.__add_entry(etr, quality, format, folder, custom_name_prefix, playlist_strict_mode, playlist_item_limit, auto_start, already, cookie_path, cookie_profile_id))
            if any(res['status'] == 'error' for res in results):
                return {'status': 'error', 'msg': ', '.join(res['msg'] for res in results if res['status'] == 'error' and 'msg' in res)}
            return {'status': 'ok'}
        elif etype == 'video' or (etype.startswith('url') and 'id' in entry and 'title' in entry):
            log.debug('Processing as a video')
            ext = str(entry.get('ext') or '').lower()
            if ext in ('unknown_video', 'unknown_audio', 'unknown'):
                log.info('Entry extension reported as unknown; delegating to proxy download workflow')
                return {'status': 'unsupported', 'msg': 'This URL looks like a direct file download and is not supported by yt-dlp.'}
            key = entry.get('webpage_url') or entry['url']
            if not self.queue.exists(key):
                original_url = entry.get('webpage_url') or entry.get('url') or key
                dl = DownloadInfo(entry['id'], entry.get('title') or entry['id'], key, quality, format, folder, custom_name_prefix, error, entry, playlist_item_limit, cookie_path, self.user_id, original_url=original_url, cookie_profile_id=cookie_profile_id)
                result = await self.__add_download(dl, auto_start, cookie_path)
                if result and result.get('status') == 'error':
                    return result
            return {'status': 'ok'}
        return {'status': 'error', 'msg': f'Unsupported resource "{etype}"'}

    async def add(self, url, quality, format, folder, custom_name_prefix, playlist_strict_mode, playlist_item_limit, auto_start=True, already=None, cookie_path=None, cookie_profile_id=None):
        log.info(f'adding {url}: {quality=} {format=} {already=} {folder=} {custom_name_prefix=} {playlist_strict_mode=} {playlist_item_limit=} {auto_start=}')
        already = set() if already is None else already
        if url in already:
            log.info('recursion detected, skipping')
            return {'status': 'ok'}
        else:
            already.add(url)
        try:
            entry = await asyncio.get_running_loop().run_in_executor(None, self.__extract_info, url, playlist_strict_mode, cookie_path)
        except yt_dlp.utils.YoutubeDLError as exc:
            msg = str(exc)
            lowered = msg.lower()
            if 'unsupported url' in lowered or 'not a valid url' in lowered or 'url does not exist' in lowered:
                return {'status': 'unsupported', 'msg': msg}
            return {'status': 'error', 'msg': msg}
        return await self.__add_entry(entry, quality, format, folder, custom_name_prefix, playlist_strict_mode, playlist_item_limit, auto_start, already, cookie_path, cookie_profile_id)

    async def start_pending(self, ids):
        for id in ids:
            if not self.pending.exists(id):
                log.warn(f'requested start for non-existent download {id}')
                continue
            dl = self.pending.get(id)
            self.queue.put(dl)
            self.pending.delete(id)
            asyncio.create_task(self.__start_download(dl))
        return {'status': 'ok'}

    async def cancel(self, ids):
        for id in ids:
            if self.pending.exists(id):
                self.pending.delete(id)
                await self.notifier.canceled(id)
                continue
            if not self.queue.exists(id):
                log.warn(f'requested cancel for non-existent download {id}')
                continue
            if self.queue.get(id).started():
                self.queue.get(id).cancel()
            else:
                self.queue.delete(id)
                await self.notifier.canceled(id)
        return {'status': 'ok'}

    async def clear(self, ids):
        deleted_files = []
        missing_files = []
        errors = {}

        for id in ids:
            if not self.done.exists(id):
                log.warn(f'requested delete for non-existent download {id}')
                continue

            dl = self.done.get(id)
            stored_filename = getattr(dl.info, 'filename', None)
            filename = stored_filename or dl.info.title
            directory = self._resolve_download_directory(dl.info)
            file_path = os.path.join(directory, stored_filename) if (directory and stored_filename) else None

            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    deleted_files.append(filename)
                except Exception as e:
                    log.warn(f'deleting file for download {id} failed with error message {e!r}')
                    errors[id] = str(e)
                    continue
            else:
                missing_files.append(filename)

            self.done.delete(id)
            await self.notifier.cleared(id)

        response = {'status': 'ok', 'deleted': deleted_files, 'missing': missing_files}
        if errors:
            response['status'] = 'error'
            response['errors'] = errors
            response['msg'] = 'Some files could not be removed from disk.'
        return response

    def get(self):
        return (list((k, v.info) for k, v in self.queue.items()) +
                list((k, v.info) for k, v in self.pending.items()),
                list((k, v.info) for k, v in self.done.items()))

    async def rename(self, id, new_name):
        if not new_name or not new_name.strip():
            return {'status': 'error', 'msg': 'New filename cannot be empty.'}

        if any(sep in new_name for sep in ('/', '\\')):
            return {'status': 'error', 'msg': 'Filename cannot contain path separators.'}

        if new_name in ('.', '..'):
            return {'status': 'error', 'msg': 'Invalid filename specified.'}

        if not self.done.exists(id):
            return {'status': 'error', 'msg': 'Download not found.'}

        dl = self.done.get(id)

        dldirectory, error_message = self.__calc_download_path(dl.info.quality, dl.info.format, dl.info.folder)
        if error_message is not None:
            return error_message

        original_path = os.path.join(dldirectory, dl.info.filename)
        if not os.path.exists(original_path):
            return {'status': 'error', 'msg': 'Original file no longer exists.'}

        target_path = os.path.join(dldirectory, new_name)

        if os.path.exists(target_path):
            return {'status': 'error', 'msg': 'A file with the requested name already exists.'}

        try:
            os.rename(original_path, target_path)
        except OSError as exc:
            log.error(f'Failed to rename file {original_path} -> {target_path}: {exc!r}')
            return {'status': 'error', 'msg': f'Failed to rename file: {exc}'}

        dl.info.filename = new_name
        dl.info.title = new_name
        try:
            dl.info.size = os.path.getsize(target_path)
        except OSError:
            dl.info.size = dl.info.size

        self.done.dict[id] = dl
        with shelve.open(self.done.path, 'w') as shelf:
            shelf[id] = dl.info

        await self.notifier.renamed(dl.info)

        return {'status': 'ok', 'filename': new_name, 'title': new_name}

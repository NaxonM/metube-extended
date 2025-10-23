#!/usr/bin/env python3
# pylint: disable=no-member,method-hidden

import base64
import os
import sys
import asyncio
import secrets
import time
import functools
from contextlib import suppress
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional
from aiohttp import web
from aiohttp.client_exceptions import ClientConnectionResetError
from aiohttp.log import access_logger
import ssl
import socket
import socketio
import logging
import json
import pathlib
import re
import uuid
import mimetypes
import psutil
from watchfiles import DefaultFilter, Change, awatch

from ytdl import DownloadQueueNotifier, DownloadQueue
from proxy_downloads import ProxyDownloadManager, ProxySettingsStore
from gallerydl_manager import (
    GalleryDlManager,
    detect_gallerydl_version,
    is_gallerydl_supported,
    list_gallerydl_sites,
)
from gallerydl_credentials import CredentialStore, CookieStore
from seedr_credentials import SeedrCredentialStore
from seedr_manager import SeedrDownloadManager
from seedrcc import AsyncSeedr
from seedrcc.exceptions import AuthenticationError, SeedrError
from ytdlp_cookies import CookieProfileStore
import importlib.util
from streaming import (
    HlsGenerationError,
    HlsStreamManager,
    HlsUnavailableError,
)


def _load_hq_module():
    module_path = Path(__file__).resolve().parent / 'hq-dl.py'
    spec = importlib.util.spec_from_file_location('hq_dl', module_path)
    if not spec or not spec.loader:
        raise ImportError('Unable to load hq-dl module')
    module = importlib.util.module_from_spec(spec)
    sys.modules['hq_dl'] = module
    spec.loader.exec_module(module)
    return module


_hq = _load_hq_module()
HQPornerError = _hq.HQPornerError
HQPornerUnsupportedError = _hq.HQPornerUnsupportedError
is_hqporner_url = _hq.is_hqporner_url
resolve_hqporner_video = _hq.resolve_hqporner_video
from yt_dlp.version import __version__ as yt_dlp_version
from auth import setup_auth
from users import UserStore
from aiohttp_session import get_session

log = logging.getLogger('main')


@functools.lru_cache(maxsize=1)
def list_ytdlp_sites():
    try:
        from yt_dlp.extractor import gen_extractors

        names = {getattr(extractor, 'IE_NAME', '') for extractor in gen_extractors()}
        return sorted(name for name in names if name)
    except Exception as exc:  # pragma: no cover
        log.warning('Failed to enumerate yt-dlp extractors: %s', exc)
        return []


@functools.lru_cache(maxsize=1)
def _get_ytdlp_extractors():
    from yt_dlp.extractor import gen_extractors

    try:
        return tuple(gen_extractors())
    except Exception as exc:  # pragma: no cover
        log.warning('Failed to cache yt-dlp extractors: %s', exc)
        return tuple()


def is_ytdlp_supported(url: str) -> bool:
    if not url:
        return False

    try:
        for extractor in _get_ytdlp_extractors():
            try:
                if extractor.suitable(url):
                    working = getattr(extractor, 'working', None)
                    if callable(working) and not working():
                        continue
                    return True
            except Exception:  # pragma: no cover - individual extractor failures shouldn't break detection
                continue
    except Exception as exc:  # pragma: no cover
        log.debug('Failed to evaluate yt-dlp support for %s: %s', url, exc)
    return False

class Config:
    _DEFAULTS = {
        'DOWNLOAD_DIR': '.',
        'AUDIO_DOWNLOAD_DIR': '%%DOWNLOAD_DIR',
        'TEMP_DIR': '%%DOWNLOAD_DIR',
        'DOWNLOAD_DIRS_INDEXABLE': 'false',
        'CUSTOM_DIRS': 'true',
        'CREATE_CUSTOM_DIRS': 'true',
        'CUSTOM_DIRS_EXCLUDE_REGEX': r'(^|/)[.@].*$',
        'DELETE_FILE_ON_TRASHCAN': 'false',
        'STATE_DIR': '.',
        'URL_PREFIX': '',
        'PUBLIC_HOST_URL': 'download/',
        'PUBLIC_HOST_AUDIO_URL': 'audio_download/',
        'OUTPUT_TEMPLATE': '%(title)s.%(ext)s',
        'OUTPUT_TEMPLATE_CHAPTER': '%(title)s - %(section_number)s %(section_title)s.%(ext)s',
        'OUTPUT_TEMPLATE_PLAYLIST': '%(playlist_title)s/%(title)s.%(ext)s',
        'DEFAULT_OPTION_PLAYLIST_STRICT_MODE' : 'true',
        'DEFAULT_OPTION_PLAYLIST_ITEM_LIMIT' : '0',
        'YTDL_OPTIONS': '{}',
        'YTDL_OPTIONS_FILE': '',
        'ROBOTS_TXT': '',
        'HOST': '0.0.0.0',
        'PORT': '8081',
        'HTTPS': 'false',
        'CERTFILE': '',
        'KEYFILE': '',
        'BASE_DIR': '',
        'DEFAULT_THEME': 'auto',
        'DOWNLOAD_MODE': 'limited',
        'MAX_CONCURRENT_DOWNLOADS': 3,
        'LOGLEVEL': 'INFO',
        'ENABLE_ACCESSLOG': 'false',
        'ADMIN_USERNAME': '',
        'ADMIN_PASSWORD': '',
        'SECRET_KEY': '',
        'LOGIN_RATELIMIT': '10/minute',
        'PROXY_DOWNLOAD_LIMIT_ENABLED': 'false',
        'PROXY_DOWNLOAD_LIMIT_MB': '0',
        'GALLERY_DL_EXEC': '/usr/local/bin/gallery-dl',
        'MAX_HISTORY_ITEMS': '200',
        'STREAM_TRANSCODE_ENABLED': 'true',
        'STREAM_TRANSCODE_TTL_SECONDS': '1200',
        'STREAM_TRANSCODE_FFMPEG': 'ffmpeg',
        'STREAM_TRANSCODE_CPU_LIMIT_PERCENT': '30',
        'STREAM_TRANSCODE_MEMORY_LIMIT_PERCENT': '40',
    }

    _BOOLEAN = ('DOWNLOAD_DIRS_INDEXABLE', 'CUSTOM_DIRS', 'CREATE_CUSTOM_DIRS', 'DELETE_FILE_ON_TRASHCAN', 'DEFAULT_OPTION_PLAYLIST_STRICT_MODE', 'HTTPS', 'ENABLE_ACCESSLOG', 'PROXY_DOWNLOAD_LIMIT_ENABLED', 'STREAM_TRANSCODE_ENABLED')

    def __init__(self):
        for k, v in self._DEFAULTS.items():
            setattr(self, k, os.environ.get(k, v))

        for k, v in self.__dict__.items():
            if isinstance(v, str) and v.startswith('%%'):
                setattr(self, k, getattr(self, v[2:]))
            if k in self._BOOLEAN:
                if v not in ('true', 'false', 'True', 'False', 'on', 'off', '1', '0'):
                    log.error(f'Environment variable "{k}" is set to a non-boolean value "{v}"')
                    sys.exit(1)
                setattr(self, k, v in ('true', 'True', 'on', '1'))

        if not self.URL_PREFIX.endswith('/'):
            self.URL_PREFIX += '/'

        # Convert relative addresses to absolute addresses to prevent the failure of file address comparison
        if self.YTDL_OPTIONS_FILE and self.YTDL_OPTIONS_FILE.startswith('.'):
            self.YTDL_OPTIONS_FILE = str(Path(self.YTDL_OPTIONS_FILE).resolve())

        success,_ = self.load_ytdl_options()
        if not success:
            sys.exit(1)

    def load_ytdl_options(self) -> tuple[bool, str]:
        try:
            self.YTDL_OPTIONS = json.loads(os.environ.get('YTDL_OPTIONS', '{}'))
            assert isinstance(self.YTDL_OPTIONS, dict)
        except (json.decoder.JSONDecodeError, AssertionError):
            msg = 'Environment variable YTDL_OPTIONS is invalid'
            log.error(msg)
            return (False, msg)

        if not self.YTDL_OPTIONS_FILE:
            return (True, '')

        log.info(f'Loading yt-dlp custom options from "{self.YTDL_OPTIONS_FILE}"')
        if not os.path.exists(self.YTDL_OPTIONS_FILE):
            msg = f'File "{self.YTDL_OPTIONS_FILE}" not found'
            log.error(msg)
            return (False, msg)
        try:
            with open(self.YTDL_OPTIONS_FILE) as json_data:
                opts = json.load(json_data)
            assert isinstance(opts, dict)
        except (json.decoder.JSONDecodeError, AssertionError):
            msg = 'YTDL_OPTIONS_FILE contents is invalid'
            log.error(msg)
            return (False, msg)

        self.YTDL_OPTIONS.update(opts)
        return (True, '')

config = Config()

gallery_dl_version = detect_gallerydl_version(getattr(config, 'GALLERY_DL_EXEC', 'gallery-dl'))

try:
    default_proxy_limit_mb = int(getattr(config, 'PROXY_DOWNLOAD_LIMIT_MB', 0))
except (TypeError, ValueError):
    default_proxy_limit_mb = 0

proxy_settings = ProxySettingsStore(
    os.path.join(config.STATE_DIR, 'proxy_settings.json'),
    bool(getattr(config, 'PROXY_DOWNLOAD_LIMIT_ENABLED', False)),
    max(default_proxy_limit_mb, 0)
)

user_store_path = os.path.join(config.STATE_DIR, 'users.json')
user_store = UserStore(user_store_path)

def ensure_default_admin():
    users = user_store.list_users(include_sensitive=True)
    if users:
        return

    username = config.ADMIN_USERNAME or 'admin'
    if config.ADMIN_PASSWORD:
        password = config.ADMIN_PASSWORD
        created_default_password = False
    else:
        password = secrets.token_urlsafe(12)
        created_default_password = True

    user_store.create_user(username, password, role='admin')
    if created_default_password:
        log.warning("Created default admin user. Please update the password immediately.")
        log.warning(f"Generated admin credentials -> username: {username}, password: {password}")


ensure_default_admin()

gallerydl_state_dir = os.path.join(config.STATE_DIR, 'gallerydl')
_gallery_credential_stores: Dict[str, CredentialStore] = {}
_gallery_cookie_stores: Dict[str, CookieStore] = {}
ytdlp_cookie_stores: Dict[str, CookieProfileStore] = {}
seedr_state_dir = os.path.join(config.STATE_DIR, 'seedr')
os.makedirs(seedr_state_dir, exist_ok=True)
_seedr_token_stores: Dict[str, SeedrCredentialStore] = {}


def _ensure_gallerydl_user_dir(user_id: str) -> str:
    path = os.path.join(gallerydl_state_dir, user_id)
    os.makedirs(path, exist_ok=True)
    return path


def get_gallery_credential_store(user_id: str) -> CredentialStore:
    user_dir = _ensure_gallerydl_user_dir(user_id)
    store = _gallery_credential_stores.get(user_dir)
    if store is None:
        store = CredentialStore(user_dir, config.SECRET_KEY)
        _gallery_credential_stores[user_dir] = store
    return store


def get_gallery_cookie_store(user_id: str) -> CookieStore:
    user_dir = _ensure_gallerydl_user_dir(user_id)
    store = _gallery_cookie_stores.get(user_dir)
    if store is None:
        store = CookieStore(user_dir)
        _gallery_cookie_stores[user_dir] = store
    return store


def _ensure_seedr_user_dir(user_id: str) -> str:
    path = os.path.join(seedr_state_dir, user_id)
    os.makedirs(path, exist_ok=True)
    return path


def get_seedr_token_store(user_id: str) -> SeedrCredentialStore:
    user_dir = _ensure_seedr_user_dir(user_id)
    store = _seedr_token_stores.get(user_dir)
    if store is None:
        secret_key = getattr(config, 'SECRET_KEY', '')
        try:
            store = SeedrCredentialStore(user_dir, secret_key)
        except ValueError as exc:
            log.error('Failed to initialise Seedr credential store for %s: %s', user_id, exc)
            raise web.HTTPInternalServerError(
                text='Seedr integration requires SECRET_KEY to be a 64-character hexadecimal string.'
            )
        _seedr_token_stores[user_dir] = store
    return store

class ObjectSerializer(json.JSONEncoder):
    def default(self, obj):
        # First try to use __dict__ for custom objects
        if hasattr(obj, '__dict__'):
            return obj.__dict__
        # Convert iterables (generators, dict_items, etc.) to lists
        # Exclude strings and bytes which are also iterable
        elif hasattr(obj, '__iter__') and not isinstance(obj, (str, bytes)):
            try:
                return list(obj)
            except:
                pass
        # Fall back to default behavior
        return json.JSONEncoder.default(self, obj)

COOKIE_ERROR_MARKERS = (
    'cookies are no longer valid',
    "sign in to confirm you're not a bot",
    "sign in to confirm you’re not a bot",
    'use --cookies',
    'cookies for the authentication',
    'please sign in',
)


def is_cookie_error_message(message: Optional[str]) -> bool:
    if not message:
        return False
    lowered = message.lower()
    return any(marker in lowered for marker in COOKIE_ERROR_MARKERS)


class CookieStatusStore:
    def __init__(self):
        self._states: Dict[str, Dict[str, Any]] = {}

    def _ensure(self, user_id: str) -> Dict[str, Any]:
        state = self._states.get(user_id)
        if state is None:
            state = {
                'has_cookies': False,
                'state': 'missing',
                'message': None,
                'checked_at': None,
            }
            self._states[user_id] = state
        return state

    def sync_presence(self, user_id: str, has_cookies: bool) -> Dict[str, Any]:
        state = self._ensure(user_id)
        if has_cookies:
            state['has_cookies'] = True
            if state['state'] == 'missing':
                state['state'] = 'unknown'
                state['message'] = None
                state['checked_at'] = None
        else:
            state['has_cookies'] = False
            state['state'] = 'missing'
            state['message'] = None
            state['checked_at'] = time.time()
        return dict(state)

    def mark_unknown(self, user_id: str) -> Dict[str, Any]:
        state = self._ensure(user_id)
        state['has_cookies'] = True
        state['state'] = 'unknown'
        state['message'] = None
        state['checked_at'] = time.time()
        return dict(state)

    def mark_valid(self, user_id: str) -> Dict[str, Any]:
        state = self._ensure(user_id)
        state['has_cookies'] = True
        state['state'] = 'valid'
        state['message'] = None
        state['checked_at'] = time.time()
        return dict(state)

    def mark_invalid(self, user_id: str, message: Optional[str] = None) -> Dict[str, Any]:
        state = self._ensure(user_id)
        state['has_cookies'] = True
        state['state'] = 'invalid'
        state['message'] = message
        state['checked_at'] = time.time()
        return dict(state)

    def clear(self, user_id: str) -> Dict[str, Any]:
        state = self._ensure(user_id)
        state['has_cookies'] = False
        state['state'] = 'missing'
        state['message'] = None
        state['checked_at'] = time.time()
        return dict(state)

    def get(self, user_id: str) -> Dict[str, Any]:
        state = self._ensure(user_id)
        return dict(state)


serializer = ObjectSerializer()
cookie_status_store = CookieStatusStore()
app = web.Application()
sio = socketio.AsyncServer(cors_allowed_origins='*', cors_credentials=True)
sio.attach(app, socketio_path=config.URL_PREFIX + 'socket.io')
routes = web.RouteTableDef()
MAX_STREAM_CHUNK = 4 * 1024 * 1024  # 4MB chunks for ranged streaming
DEFAULT_YTDLP_HOSTS = ['youtube.com', 'youtu.be', 'music.youtube.com']


class UserNotifier(DownloadQueueNotifier):
    def __init__(self, sio_server: socketio.AsyncServer, user_id: str):
        self.sio = sio_server
        self.user_id = user_id
        self._room = f'user:{user_id}'

    async def added(self, dl):
        log.info(f"Notifier[{self.user_id}]: Download added - {dl.title}")
        await self.sio.emit('added', serializer.encode(dl), room=self._room)

    async def updated(self, dl):
        log.info(f"Notifier[{self.user_id}]: Download updated - {dl.title}")
        await self.sio.emit('updated', serializer.encode(dl), room=self._room)

    async def completed(self, dl):
        log.info(f"Notifier[{self.user_id}]: Download completed - {dl.title}")
        await self.sio.emit('completed', serializer.encode(dl), room=self._room)

    async def canceled(self, id):
        log.info(f"Notifier[{self.user_id}]: Download canceled - {id}")
        await self.sio.emit('canceled', serializer.encode(id), room=self._room)

    async def cleared(self, id):
        log.info(f"Notifier[{self.user_id}]: Download cleared - {id}")
        await self.sio.emit('cleared', serializer.encode(id), room=self._room)

    async def renamed(self, dl):
        log.info(f"Notifier[{self.user_id}]: Download renamed - {dl.title}")
        await self.sio.emit('renamed', serializer.encode(dl), room=self._room)


class DownloadManager:
    def __init__(
        self,
        config,
        sio_server: socketio.AsyncServer,
        proxy_settings: ProxySettingsStore,
        cookie_status_store: CookieStatusStore,
    ):
        self.config = config
        self.sio = sio_server
        self._queues: Dict[str, DownloadQueue] = {}
        self._proxy_queues: Dict[str, ProxyDownloadManager] = {}
        self._gallery_queues: Dict[str, GalleryDlManager] = {}
        self._seedr_queues: Dict[str, "SeedrDownloadManager"] = {}
        self._notifiers: Dict[str, UserNotifier] = {}
        self.proxy_settings = proxy_settings
        self.cookie_status_store = cookie_status_store
        self._lock = asyncio.Lock()
        try:
            self.max_history_items = max(0, int(getattr(self.config, 'MAX_HISTORY_ITEMS', 200)))
        except (TypeError, ValueError):
            self.max_history_items = 200

    def _state_dir_for(self, user_id: str) -> str:
        path = os.path.join(self.config.STATE_DIR, 'users', user_id)
        os.makedirs(path, exist_ok=True)
        return path

    async def get_queue(self, user_id: str) -> DownloadQueue:
        if user_id in self._queues:
            return self._queues[user_id]

        async with self._lock:
            if user_id in self._queues:
                return self._queues[user_id]

            notifier = self._notifiers.get(user_id)
            if notifier is None:
                notifier = UserNotifier(self.sio, user_id)
                self._notifiers[user_id] = notifier

            queue = DownloadQueue(
                self.config,
                notifier,
                state_dir=self._state_dir_for(user_id),
                user_id=user_id,
                cookie_status_store=self.cookie_status_store,
                download_limit_source=self.proxy_settings,
                max_history_items=self.max_history_items,
            )
            await queue.initialize()
            self._queues[user_id] = queue

            proxy_queue = ProxyDownloadManager(
                self.config,
                notifier,
                queue,
                self._state_dir_for(user_id),
                user_id,
                self.proxy_settings,
                max_history_items=self.max_history_items,
            )
            self._proxy_queues[user_id] = proxy_queue

            gallery_queue = GalleryDlManager(
                self.config,
                notifier,
                self._state_dir_for(user_id),
                executable_path=getattr(self.config, 'GALLERY_DL_EXEC', 'gallery-dl'),
                credential_store=get_gallery_credential_store(user_id),
                cookie_store=get_gallery_cookie_store(user_id),
                max_history_items=self.max_history_items,
            )
            self._gallery_queues[user_id] = gallery_queue

            seedr_queue = SeedrDownloadManager(
                self.config,
                notifier,
                base_queue=queue,
                state_dir=self._state_dir_for(user_id),
                user_id=user_id,
                token_store=get_seedr_token_store(user_id),
                max_history_items=self.max_history_items,
            )
            await seedr_queue.initialize()
            self._seedr_queues[user_id] = seedr_queue

            return queue

    async def get_proxy_queue(self, user_id: str) -> ProxyDownloadManager:
        if user_id not in self._proxy_queues:
            await self.get_queue(user_id)
        return self._proxy_queues[user_id]

    async def get_gallery_queue(self, user_id: str) -> GalleryDlManager:
        if user_id not in self._gallery_queues:
            await self.get_queue(user_id)
        return self._gallery_queues[user_id]

    async def get_seedr_queue(self, user_id: str) -> "SeedrDownloadManager":
        if user_id not in self._seedr_queues:
            await self.get_queue(user_id)
        return self._seedr_queues[user_id]

    async def get_combined_state(self, user_id: str):
        queue = await self.get_queue(user_id)
        proxy_queue = await self.get_proxy_queue(user_id)
        gallery_queue = await self.get_gallery_queue(user_id)
        seedr_queue = await self.get_seedr_queue(user_id)
        primary_queue, primary_done = queue.get()
        proxy_queue_items, proxy_done_items = proxy_queue.get()
        gallery_queue_items, gallery_done_items = gallery_queue.get()
        seedr_queue_items, seedr_done_items = seedr_queue.get()
        return (
            primary_queue + proxy_queue_items + gallery_queue_items + seedr_queue_items,
            primary_done + proxy_done_items + gallery_done_items + seedr_done_items,
        )


download_manager = DownloadManager(
    config,
    sio,
    proxy_settings,
    cookie_status_store,
)

try:
    ttl_seconds = int(getattr(config, 'STREAM_TRANSCODE_TTL_SECONDS', 1200))
except (TypeError, ValueError):
    ttl_seconds = 1200

def _coerce_percent(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num <= 0:
        return None
    return num

cpu_limit_percent = _coerce_percent(getattr(config, 'STREAM_TRANSCODE_CPU_LIMIT_PERCENT', None))
memory_limit_percent = _coerce_percent(getattr(config, 'STREAM_TRANSCODE_MEMORY_LIMIT_PERCENT', None))

stream_hls_manager = HlsStreamManager(
    os.path.join(config.STATE_DIR, 'hls'),
    ffmpeg_path=getattr(config, 'STREAM_TRANSCODE_FFMPEG', 'ffmpeg'),
    enabled=bool(getattr(config, 'STREAM_TRANSCODE_ENABLED', True)),
    ttl_seconds=max(ttl_seconds, 300),
    cpu_limit_percent=cpu_limit_percent,
    memory_limit_percent=memory_limit_percent,
)


def refresh_stream_transcode_status() -> bool:
    previous = (
        getattr(config, 'STREAM_TRANSCODE_AVAILABLE', None),
        getattr(config, 'STREAM_TRANSCODE_STATUS', None),
        getattr(config, 'STREAM_TRANSCODE_MESSAGE', None),
    )
    config.STREAM_TRANSCODE_AVAILABLE = stream_hls_manager.enabled
    config.STREAM_TRANSCODE_STATUS = stream_hls_manager.status_code()
    config.STREAM_TRANSCODE_MESSAGE = stream_hls_manager.status_message()
    current = (
        config.STREAM_TRANSCODE_AVAILABLE,
        config.STREAM_TRANSCODE_STATUS,
        config.STREAM_TRANSCODE_MESSAGE,
    )
    return current != previous


refresh_stream_transcode_status()


class StreamTarget(NamedTuple):
    file_path: str
    base_directory: str


def _decode_stream_token(token: str) -> str:
    padding = '=' * (-len(token) % 4)
    try:
        return base64.urlsafe_b64decode(token + padding).decode('utf-8')
    except Exception:
        raise web.HTTPNotFound(text='Invalid stream identifier')


def _path_is_inside(path: str, base: str) -> bool:
    try:
        normalized_path = os.path.abspath(path)
        normalized_base = os.path.abspath(base)
        return os.path.commonpath([normalized_path, normalized_base]) == normalized_base
    except (ValueError, OSError):
        return False


def _sanitize_segment_name(name: str) -> str:
    if not name:
        raise web.HTTPNotFound()
    if '/' in name or '\\' in name:
        raise web.HTTPNotFound()
    if name.startswith('.'):
        raise web.HTTPNotFound()
    return name


async def resolve_stream_target(user_id: str, download_id: str) -> StreamTarget:
    queue = await download_manager.get_queue(user_id)
    if queue.done.exists(download_id):
        dl = queue.done.get(download_id)
        info = dl.info
        filename = getattr(info, 'filename', None)
        if filename:
            directory = queue._resolve_download_directory(info)
            if directory:
                file_path = os.path.abspath(os.path.normpath(os.path.join(directory, filename)))
                base_directory = os.path.abspath(directory)
                if os.path.isfile(file_path) and _path_is_inside(file_path, base_directory):
                    return StreamTarget(file_path=file_path, base_directory=base_directory)
                if not os.path.isfile(file_path):
                    log.debug(
                        'Adaptive streaming file missing (user=%s download=%s path=%s)',
                        user_id,
                        download_id,
                        file_path,
                    )
                elif not _path_is_inside(file_path, base_directory):
                    log.warning(
                        'Adaptive streaming prevented by sandbox violation (user=%s download=%s path=%s base=%s)',
                        user_id,
                        download_id,
                        file_path,
                        base_directory,
                    )
            else:
                log.debug(
                    'Adaptive streaming directory could not be resolved (user=%s download=%s folder=%r)',
                    user_id,
                    download_id,
                    getattr(info, 'folder', None),
                )
        log.debug(
            'Adaptive streaming target unavailable for download=%s (user=%s): filename=%r directory=%r',
            download_id,
            user_id,
            filename,
            directory if 'directory' in locals() else None,
        )
        raise web.HTTPNotFound(text='File not available for streaming')

    proxy_queue = await download_manager.get_proxy_queue(user_id)
    proxy_job = proxy_queue.get_done(download_id)
    if proxy_job and proxy_job.file_path:
        file_path = os.path.abspath(os.path.normpath(proxy_job.file_path))
        base_directory = os.path.abspath(os.path.dirname(proxy_job.file_path))
        if os.path.isfile(file_path) and _path_is_inside(file_path, base_directory):
            return StreamTarget(file_path=file_path, base_directory=base_directory)

    gallery_queue = await download_manager.get_gallery_queue(user_id)
    try:
        gallery_job = gallery_queue.done.get(download_id)
    except (AttributeError, KeyError):  # pragma: no cover - defensive for unexpected storage implementations
        gallery_job = None
    if gallery_job and getattr(gallery_job, 'archive_path', None):
        raise web.HTTPNotFound(text='Streaming archives is not supported')

    seedr_queue = await download_manager.get_seedr_queue(user_id)
    seedr_job = seedr_queue.get_done(download_id)
    if seedr_job and seedr_job.file_path and os.path.exists(seedr_job.file_path):
        file_path = os.path.abspath(os.path.normpath(seedr_job.file_path))
        base_directory = os.path.abspath(os.path.dirname(seedr_job.file_path))
        if os.path.isfile(file_path) and _path_is_inside(file_path, base_directory):
            return StreamTarget(file_path=file_path, base_directory=base_directory)

    log.debug('Adaptive streaming target not found for download=%s (user=%s)', download_id, user_id)
    raise web.HTTPNotFound(text='Download not found')


async def require_user_session(request):
    session = await get_session(request)
    user_id = session.get('user_id')
    if not user_id:
        raise web.HTTPUnauthorized()
    return session, user_id


async def get_user_context(request):
    session = await get_session(request)
    user_id = session.get('user_id')
    if not user_id:
        raise web.HTTPUnauthorized()
    queue = await download_manager.get_queue(user_id)
    return session, user_id, queue


def ensure_admin(session):
    if session.get('role') != 'admin':
        raise web.HTTPForbidden(text='Admin privileges required')


def _has_other_active_admins(exclude_id: Optional[str] = None) -> bool:
    for user in user_store.list_users(include_sensitive=True):
        if user.get('role') != 'admin':
            continue
        if user.get('disabled'):
            continue
        if exclude_id and user.get('id') == exclude_id:
            continue
        return True
    return False

class FileOpsFilter(DefaultFilter):
    def __call__(self, change_type: int, path: str) -> bool:
        # Check if this path matches our YTDL_OPTIONS_FILE
        if path != config.YTDL_OPTIONS_FILE:
            return False

        # For existing files, use samefile comparison to handle symlinks correctly
        if os.path.exists(config.YTDL_OPTIONS_FILE):
            try:
                if not os.path.samefile(path, config.YTDL_OPTIONS_FILE):
                    return False
            except (OSError, IOError):
                # If samefile fails, fall back to string comparison
                if path != config.YTDL_OPTIONS_FILE:
                    return False

        # Accept all change types for our file: modified, added, deleted
        return change_type in (Change.modified, Change.added, Change.deleted)

def get_options_update_time(success=True, msg=''):
    result = {
        'success': success,
        'msg': msg,
        'update_time': None
    }

    # Only try to get file modification time if YTDL_OPTIONS_FILE is set and file exists
    if config.YTDL_OPTIONS_FILE and os.path.exists(config.YTDL_OPTIONS_FILE):
        try:
            result['update_time'] = os.path.getmtime(config.YTDL_OPTIONS_FILE)
        except (OSError, IOError) as e:
            log.warning(f"Could not get modification time for {config.YTDL_OPTIONS_FILE}: {e}")
            result['update_time'] = None

    return result

async def watch_files():
    async def _watch_files():
        async for changes in awatch(config.YTDL_OPTIONS_FILE, watch_filter=FileOpsFilter()):
            success, msg = config.load_ytdl_options()
            result = get_options_update_time(success, msg)
            await sio.emit('ytdl_options_changed', serializer.encode(result))

    log.info(f'Starting Watch File: {config.YTDL_OPTIONS_FILE}')
    asyncio.create_task(_watch_files())

if config.YTDL_OPTIONS_FILE:
    app.on_startup.append(lambda app: watch_files())


def ensure_cookie_directory(user_id: str) -> str:
    path = os.path.join(config.STATE_DIR, 'cookies', user_id)
    os.makedirs(path, exist_ok=True)
    return path


def _parse_string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [segment.strip() for segment in value.split(',')]
    elif isinstance(value, list):
        items = []
        for item in value:
            if isinstance(item, str):
                candidate = item.strip()
                if candidate:
                    items.append(candidate)
    else:
        return []
    return [item for item in items if item]


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'on'}
    if isinstance(value, (int, float)):
        return bool(value)
    return False


def _inspect_cookie_file(path: str) -> Dict[str, Any]:
    summary: Dict[str, Any] = {'path': path}
    names = []
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            for line in fh:
                if not line or line.startswith('#'):
                    continue
                parts = line.strip().split('\t')
                if len(parts) >= 7:
                    names.append(parts[5])
        summary['cookie_count'] = len(names)
        if names:
            unique_names = sorted(set(names))
            if len(unique_names) > 8:
                summary['cookies'] = unique_names[:8] + ['…']
            else:
                summary['cookies'] = unique_names
        summary['has_sessionid'] = 'sessionid' in names
        summary['has_csrftoken'] = 'csrftoken' in names
    except OSError as exc:
        summary['error'] = str(exc)
    return summary


def get_ytdlp_cookie_store(user_id: str) -> CookieProfileStore:
    directory = os.path.join(ensure_cookie_directory(user_id), 'ytdlp')
    store = ytdlp_cookie_stores.get(directory)
    if store is None:
        store = CookieProfileStore(directory)
        ytdlp_cookie_stores[directory] = store
    return store


def get_session_identity(session) -> str:
    identity = getattr(session, 'identity', None)
    if identity:
        return identity
    identity = session.get('cookie_identity')
    if not identity:
        identity = uuid.uuid4().hex
        session['cookie_identity'] = identity
    return identity


def get_cookie_path_for_session(session) -> str:
    user_id = session.get('user_id')
    if not user_id:
        raise web.HTTPUnauthorized()
    directory = ensure_cookie_directory(user_id)
    identity = get_session_identity(session)
    return os.path.join(directory, f"{identity}.txt")


async def add_hqporner_download(
    proxy_queue: ProxyDownloadManager,
    url: str,
    quality: str,
    format_id: Optional[str],
    folder: Optional[str],
    custom_name_prefix: Optional[str],
    auto_start: bool,
) -> Dict:
    requested_format = (format_id or '').lower()
    if requested_format and requested_format not in ('', 'any', 'mp4'):
        return {
            'status': 'error',
            'msg': 'HQPorner downloads currently support MP4 format only.',
        }

    normalized_quality = (quality or '').lower()
    if normalized_quality in ('audio', 'thumbnail'):
        return {
            'status': 'error',
            'msg': 'Audio-only and thumbnail downloads are not available for HQPorner videos.',
        }

    try:
        video = await resolve_hqporner_video(url, quality or 'best')
    except HQPornerUnsupportedError as exc:
        return {'status': 'error', 'msg': str(exc)}
    except HQPornerError as exc:
        log.error('Failed to resolve HQPorner download for %s: %s', url, exc)
        return {
            'status': 'error',
            'msg': 'Unable to process HQPorner download at this time.',
        }

    title = f"{video.title} ({video.quality_label})"
    result = await proxy_queue.add_job(
        url=video.download_url,
        title=title,
        folder=folder or '',
        custom_name_prefix=custom_name_prefix or '',
        auto_start=auto_start,
        provider='hqporner',
        quality_label=video.quality_label,
        format_id='mp4',
        original_url=video.page_url,
    )

    if result.get('status') == 'ok' and 'msg' not in result:
        result['msg'] = 'HQPorner download added to the queue.'
    return result

@routes.post(config.URL_PREFIX + 'add')
async def add(request):
    log.info("Received request to add download")
    post = await request.json()
    log.info(f"Request data: {post}")
    url = post.get('url')
    quality = post.get('quality')
    if not url or not quality:
        log.error("Bad request: missing 'url' or 'quality'")
        raise web.HTTPBadRequest()
    format = post.get('format')
    folder = post.get('folder')
    custom_name_prefix = post.get('custom_name_prefix')
    playlist_strict_mode = post.get('playlist_strict_mode')
    playlist_item_limit = post.get('playlist_item_limit')
    auto_start = post.get('auto_start')

    session, user_id, queue = await get_user_context(request)
    proxy_queue: Optional[ProxyDownloadManager] = None

    legacy_cookie_path = session.get('cookie_file')
    if legacy_cookie_path:
        user_cookie_dir = ensure_cookie_directory(user_id)
        if not legacy_cookie_path.startswith(user_cookie_dir) or not os.path.exists(legacy_cookie_path):
            legacy_cookie_path = None

    raw_cookie_tags = post.get('cookie_tags')
    cookie_tags: List[str] = []
    if isinstance(raw_cookie_tags, list):
        for tag in raw_cookie_tags:
            if isinstance(tag, str):
                cleaned = tag.strip().lower()
                if cleaned:
                    cookie_tags.append(cleaned)

    requested_cookie_profile = post.get('cookie_profile_id')
    cookie_profile_id: Optional[str] = None
    cookie_path: Optional[str] = None
    ytdlp_cookie_store = get_ytdlp_cookie_store(user_id)
    if isinstance(requested_cookie_profile, str):
        entry = ytdlp_cookie_store.get_profile(requested_cookie_profile)
        if entry:
            candidate_path = ytdlp_cookie_store.resolve_profile_path(requested_cookie_profile)
            if candidate_path:
                cookie_profile_id = requested_cookie_profile
                cookie_path = candidate_path
                details = _inspect_cookie_file(candidate_path)
                log.info('yt-dlp cookie profile explicitly selected: id=%s details=%s', cookie_profile_id, details)

    if custom_name_prefix is None:
        custom_name_prefix = ''
    if auto_start is None:
        auto_start = True
    if playlist_strict_mode is None:
        playlist_strict_mode = config.DEFAULT_OPTION_PLAYLIST_STRICT_MODE
    if playlist_item_limit is None:
        playlist_item_limit = config.DEFAULT_OPTION_PLAYLIST_ITEM_LIMIT

    playlist_item_limit = int(playlist_item_limit)

    gallery_queue = await download_manager.get_gallery_queue(user_id)

    gallery_options = post.get('gallerydl_options') or []
    preferred_backend_value = post.get('preferred_backend')
    preferred_backend = preferred_backend_value.strip().lower() if isinstance(preferred_backend_value, str) else None
    if preferred_backend not in {'gallerydl', 'ytdlp'}:
        preferred_backend = None

    gallery_supported = is_gallerydl_supported(url, getattr(config, 'GALLERY_DL_EXEC', 'gallery-dl'))
    ytdlp_supported = is_ytdlp_supported(url)

    def build_gallery_prompt() -> Dict[str, Any]:
        return {
            'url': url,
            'title': post.get('title') or '',
            'auto_start': auto_start,
            'options': gallery_options,
            'credential_id': None,
            'cookie_name': None,
            'proxy': None,
            'retries': None,
            'sleep_request': None,
            'sleep_429': None,
            'write_metadata': False,
            'write_info_json': False,
            'write_tags': False,
            'download_archive': False,
            'archive_id': None,
        }

    if preferred_backend == 'gallerydl':
        if gallery_supported:
            status = {'status': 'gallerydl', 'gallerydl': build_gallery_prompt()}
        else:
            status = {'status': 'error', 'msg': 'Gallery-dl is not available for this URL.'}
        return web.Response(text=serializer.encode(status))

    if preferred_backend != 'ytdlp':
        if gallery_supported and ytdlp_supported:
            status = {
                'status': 'choose-backend',
                'backend_choice': {
                    'url': url,
                    'title': post.get('title') or '',
                    'gallerydl': build_gallery_prompt(),
                    'ytdlp': {
                        'quality': quality,
                        'format': format,
                        'folder': folder or '',
                        'custom_name_prefix': custom_name_prefix or '',
                        'playlist_strict_mode': playlist_strict_mode,
                        'playlist_item_limit': playlist_item_limit,
                        'auto_start': auto_start,
                    },
                },
            }
            return web.Response(text=serializer.encode(status))
        if gallery_supported:
            status = {'status': 'gallerydl', 'gallerydl': build_gallery_prompt()}
            return web.Response(text=serializer.encode(status))

    if is_hqporner_url(url):
        proxy_queue = await download_manager.get_proxy_queue(user_id)
        status = await add_hqporner_download(
            proxy_queue,
            url,
            quality,
            format,
            folder,
            custom_name_prefix,
            auto_start,
        )
    else:
        if cookie_path is None:
            matched_profile = ytdlp_cookie_store.auto_match_profile(url, cookie_tags)
            if matched_profile:
                candidate_path = ytdlp_cookie_store.resolve_profile_path(matched_profile.get('id'))
                if candidate_path:
                    cookie_profile_id = matched_profile.get('id')
                    cookie_path = candidate_path
                    details = _inspect_cookie_file(candidate_path)
                    log.info('yt-dlp cookie profile auto-matched: id=%s hosts=%s details=%s', cookie_profile_id, matched_profile.get('hosts'), details)
        if cookie_path is None:
            cookie_path = legacy_cookie_path
            if cookie_path:
                details = _inspect_cookie_file(cookie_path)
                log.info('yt-dlp falling back to legacy cookie file: %s details=%s', cookie_path, details)
        status = await queue.add(
            url,
            quality,
            format,
            folder,
            custom_name_prefix,
            playlist_strict_mode,
            playlist_item_limit,
            auto_start,
            cookie_path=cookie_path,
            cookie_profile_id=cookie_profile_id,
        )
        if cookie_profile_id:
            ytdlp_cookie_store.touch_profile(cookie_profile_id)
            log.info('yt-dlp cookie profile %s marked as recently used', cookie_profile_id)

    if status.get('status') == 'unsupported':
        proxy_config = await proxy_settings.get()
        status['proxy'] = {
            'url': url,
            'quality': quality,
            'format': format,
            'folder': folder or '',
            'custom_name_prefix': custom_name_prefix or '',
            'playlist_strict_mode': playlist_strict_mode,
            'playlist_item_limit': playlist_item_limit,
            'auto_start': auto_start,
            'size_limit_mb': proxy_config.get('limit_mb', 0),
            'limit_enabled': proxy_config.get('limit_enabled', False)
        }
        if not status.get('msg'):
            status['msg'] = 'This URL is not supported by yt-dlp. You can still download it directly through the server.'
    elif status.get('status') == 'error' and cookie_path and is_cookie_error_message(status.get('msg')):
        cookie_status_store.mark_invalid(user_id, status.get('msg'))
    return web.Response(text=serializer.encode(status))

@routes.post(config.URL_PREFIX + 'delete')
async def delete(request):
    post = await request.json()
    ids = post.get('ids')
    where = post.get('where')
    if not ids or where not in ['queue', 'done']:
        log.error("Bad request: missing 'ids' or incorrect 'where' value")
        raise web.HTTPBadRequest()
    _session, user_id, queue = await get_user_context(request)
    proxy_queue = await download_manager.get_proxy_queue(user_id)
    gallery_queue = await download_manager.get_gallery_queue(user_id)
    seedr_queue = await download_manager.get_seedr_queue(user_id)

    if where == 'queue':
        results = [
            await queue.cancel(ids),
            await proxy_queue.cancel(ids),
            await gallery_queue.cancel(ids),
            await seedr_queue.cancel(ids),
        ]
        status = next((res for res in results if res.get('status') == 'error'), {'status': 'ok'})
    else:
        primary = await queue.clear(ids)
        secondary = await proxy_queue.clear(ids)
        gallery = await gallery_queue.clear(ids)
        seedr = await seedr_queue.clear(ids)
        deleted = (primary.get('deleted') or []) + (secondary.get('deleted') or []) + (gallery.get('deleted') or []) + (seedr.get('deleted') or [])
        missing = (primary.get('missing') or []) + (secondary.get('missing') or []) + (gallery.get('missing') or []) + (seedr.get('missing') or [])
        status = {'status': 'ok', 'deleted': deleted, 'missing': missing}
        errors = {}
        if primary.get('status') == 'error':
            errors.update(primary.get('errors') or {})
        if secondary.get('status') == 'error':
            errors.update(secondary.get('errors') or {})
        if gallery.get('status') == 'error':
            errors.update(gallery.get('errors') or {})
        if seedr.get('status') == 'error':
            errors.update(seedr.get('errors') or {})
        if errors:
            status.update({'status': 'error', 'errors': errors, 'msg': 'Some files could not be removed from disk.'})
    log.info(f"Download delete request processed for ids: {ids}, where: {where}")
    return web.Response(text=serializer.encode(status))

@routes.post(config.URL_PREFIX + 'start')
async def start(request):
    post = await request.json()
    ids = post.get('ids')
    log.info(f"Received request to start pending downloads for ids: {ids}")
    _session, user_id, queue = await get_user_context(request)
    proxy_queue = await download_manager.get_proxy_queue(user_id)
    gallery_queue = await download_manager.get_gallery_queue(user_id)
    seedr_queue = await download_manager.get_seedr_queue(user_id)
    results = [
        await queue.start_pending(ids),
        await proxy_queue.start_jobs(ids),
        await gallery_queue.start_jobs(ids),
        await seedr_queue.start_jobs(ids),
    ]
    status = next((res for res in results if res.get('status') == 'error'), {'status': 'ok'})
    return web.Response(text=serializer.encode(status))

@routes.post(config.URL_PREFIX + 'rename')
async def rename(request):
    post = await request.json()
    id = post.get('id')
    new_name = post.get('new_name')
    if not id or new_name is None:
        log.error("Bad request: missing 'id' or 'new_name'")
        raise web.HTTPBadRequest()
    _session, user_id, queue = await get_user_context(request)
    status = await queue.rename(id, new_name)
    if status.get('status') == 'error' and 'Download not found' in (status.get('msg') or ''):
        proxy_queue = await download_manager.get_proxy_queue(user_id)
        status = await proxy_queue.rename(id, new_name)
        if status.get('status') == 'error' and 'Download not found' in (status.get('msg') or ''):
            gallery_queue = await download_manager.get_gallery_queue(user_id)
            status = await gallery_queue.rename(id, new_name)
            if status.get('status') == 'error' and 'Download not found' in (status.get('msg') or ''):
                seedr_queue = await download_manager.get_seedr_queue(user_id)
                status = await seedr_queue.rename(id, new_name)
    log.info(f"Rename request processed for id: {id}")
    return web.Response(text=serializer.encode(status))


@routes.get(config.URL_PREFIX + 'seedr/status')
async def seedr_status(request):
    _session, user_id, _ = await get_user_context(request)
    try:
        store = get_seedr_token_store(user_id)
    except web.HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - unexpected
        log.error('Failed to resolve Seedr credential store for %s: %s', user_id, exc)
        raise web.HTTPInternalServerError(text='Seedr integration is currently unavailable.')

    status = store.status()
    status['status'] = 'ok'
    return web.Response(text=serializer.encode(status))


@routes.post(config.URL_PREFIX + 'seedr/device/start')
async def seedr_device_start(request):
    _session, user_id, _ = await get_user_context(request)
    try:
        store = get_seedr_token_store(user_id)
    except web.HTTPException:
        raise
    except Exception as exc:  # pragma: no cover
        log.error('Failed to resolve Seedr credential store for %s: %s', user_id, exc)
        raise web.HTTPInternalServerError(text='Seedr integration is currently unavailable.')

    device = await AsyncSeedr.get_device_code()
    challenge_payload = {
        'device_code': device.device_code,
        'user_code': device.user_code,
        'verification_url': device.verification_url,
        'interval': device.interval,
        'expires_in': device.expires_in,
        'expires_at': time.time() + max(device.expires_in, 0),
    }
    store.save_device_challenge(challenge_payload)

    response = {
        'status': 'ok',
        'challenge': {
            'device_code': device.device_code,
            'user_code': device.user_code,
            'verification_url': device.verification_url,
            'interval': device.interval,
            'expires_in': device.expires_in,
        },
    }
    return web.Response(text=serializer.encode(response))


@routes.post(config.URL_PREFIX + 'seedr/device/complete')
async def seedr_device_complete(request):
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            payload = {}
    except json.JSONDecodeError:
        payload = {}

    _session, user_id, _ = await get_user_context(request)
    try:
        store = get_seedr_token_store(user_id)
    except web.HTTPException:
        raise
    except Exception as exc:  # pragma: no cover
        log.error('Failed to resolve Seedr credential store for %s: %s', user_id, exc)
        raise web.HTTPInternalServerError(text='Seedr integration is currently unavailable.')

    device_code = payload.get('device_code') if isinstance(payload.get('device_code'), str) else None
    challenge = store.load_device_challenge()
    if not device_code:
        device_code = challenge.get('device_code') if challenge else None

    if not device_code:
        return web.Response(text=serializer.encode({'status': 'error', 'msg': 'No pending Seedr device authorization found.'}))

    try:
        client = await AsyncSeedr.from_device_code(device_code)
    except AuthenticationError as exc:
        message = str(exc) or 'Seedr authorization is not yet complete. Please approve the device code and try again.'
        return web.Response(text=serializer.encode({'status': 'error', 'msg': message}))
    except SeedrError as exc:  # pragma: no cover - unexpected third-party failure
        log.error('Seedr device authorization failed for %s: %s', user_id, exc)
        return web.Response(text=serializer.encode({'status': 'error', 'msg': 'Seedr authorization failed. Please try again.'}))

    try:
        settings = await client.get_settings()
        account_raw = settings.account.get_raw()
        account_summary = {
            'username': account_raw.get('username'),
            'user_id': account_raw.get('user_id'),
            'premium': account_raw.get('premium'),
            'space_used': account_raw.get('space_used'),
            'space_max': account_raw.get('space_max'),
            'bandwidth_used': account_raw.get('bandwidth_used'),
            'country': settings.country,
        }
        store.save_token(client.token, account_summary)
        store.clear_device_challenge()
        response = {'status': 'ok', 'account': account_summary}
    except SeedrError as exc:  # pragma: no cover - third-party failure path
        await client.close()
        log.error('Fetching Seedr account details failed for %s: %s', user_id, exc)
        return web.Response(text=serializer.encode({'status': 'error', 'msg': 'Failed to finalise Seedr authorization.'}))
    except Exception:
        await client.close()
        raise

    await client.close()
    return web.Response(text=serializer.encode(response))


@routes.post(config.URL_PREFIX + 'seedr/logout')
async def seedr_logout(request):
    _session, user_id, _ = await get_user_context(request)
    try:
        store = get_seedr_token_store(user_id)
    except web.HTTPException:
        raise
    except Exception as exc:  # pragma: no cover
        log.error('Failed to resolve Seedr credential store for %s: %s', user_id, exc)
        raise web.HTTPInternalServerError(text='Seedr integration is currently unavailable.')

    store.clear_token()
    store.clear_device_challenge()
    return web.Response(text=serializer.encode({'status': 'ok'}))


def _extract_magnet_links(payload: Dict[str, Any]) -> List[str]:
    links: List[str] = []
    single = payload.get('magnet') or payload.get('magnet_link')
    if isinstance(single, str) and single.strip():
        links.append(single.strip())

    batch = payload.get('magnet_links')
    if isinstance(batch, list):
        for item in batch:
            if isinstance(item, str) and item.strip():
                links.append(item.strip())

    text_block = payload.get('magnet_text')
    if isinstance(text_block, str):
        for line in text_block.splitlines():
            line = line.strip()
            if line:
                links.append(line)

    # Deduplicate while preserving order
    seen = set()
    result: List[str] = []
    for link in links:
        if link not in seen:
            seen.add(link)
            result.append(link)
    return result


@routes.post(config.URL_PREFIX + 'seedr/add')
async def seedr_add(request):
    try:
        post = await request.json()
        if not isinstance(post, dict):
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        raise web.HTTPBadRequest(text='Invalid JSON payload')

    magnet_links = _extract_magnet_links(post)
    torrent_file = post.get('torrent_file') if isinstance(post.get('torrent_file'), str) else None

    if not magnet_links and not torrent_file:
        raise web.HTTPBadRequest(text='Provide at least one magnet link or a torrent_file reference.')

    folder = post.get('folder') or ''
    custom_name_prefix = post.get('custom_name_prefix') or ''
    auto_start = bool(post.get('auto_start', True))
    folder_id = post.get('folder_id') or '-1'

    _session, user_id, _ = await get_user_context(request)
    seedr_queue = await download_manager.get_seedr_queue(user_id)

    responses: List[Dict[str, Any]] = []
    if torrent_file and not magnet_links:
        result = await seedr_queue.add_job(
            torrent_file=torrent_file,
            title=post.get('title'),
            folder=folder,
            custom_name_prefix=custom_name_prefix,
            auto_start=auto_start,
            folder_id=str(folder_id),
        )
        return web.Response(text=serializer.encode(result))

    for link in magnet_links:
        result = await seedr_queue.add_job(
            magnet_link=link,
            title=post.get('title'),
            folder=folder,
            custom_name_prefix=custom_name_prefix,
            auto_start=auto_start,
            folder_id=str(folder_id),
        )
        responses.append(result)

    if len(responses) == 1:
        return web.Response(text=serializer.encode(responses[0]))
    return web.Response(text=serializer.encode({'status': 'ok', 'results': responses, 'count': len(responses)}))


@routes.post(config.URL_PREFIX + 'seedr/upload')
async def seedr_upload(request):
    _session, user_id, _ = await get_user_context(request)
    seedr_queue = await download_manager.get_seedr_queue(user_id)

    reader = await request.multipart()
    if reader is None:
        raise web.HTTPBadRequest(text='Expected multipart form data')

    upload_fields: Dict[str, str] = {}
    saved_path: Optional[str] = None
    original_name: Optional[str] = None

    async for part in reader:
        if part.name == 'file':
            if not part.filename:
                raise web.HTTPBadRequest(text='torrent file is required')
            original_name = part.filename
            safe_name = re.sub(r'[^A-Za-z0-9._-]+', '_', original_name)
            if not safe_name:
                safe_name = 'torrent'
            user_dir = _ensure_seedr_user_dir(user_id)
            upload_dir = os.path.join(user_dir, 'uploads')
            os.makedirs(upload_dir, exist_ok=True)
            extension = os.path.splitext(safe_name)[1] or '.torrent'
            temp_name = f"{uuid.uuid4().hex}{extension}"
            temp_path = os.path.join(upload_dir, temp_name)
            with open(temp_path, 'wb') as fh:
                while True:
                    chunk = await part.read_chunk()
                    if not chunk:
                        break
                    fh.write(chunk)
            saved_path = temp_path
        else:
            value = await part.text()
            upload_fields[part.name] = value

    if saved_path is None:
        raise web.HTTPBadRequest(text='torrent file is required')

    folder = upload_fields.get('folder') or ''
    custom_name_prefix = upload_fields.get('custom_name_prefix') or ''
    folder_id = upload_fields.get('folder_id') or '-1'
    auto_start_raw = upload_fields.get('auto_start')
    auto_start = True
    if isinstance(auto_start_raw, str):
        auto_start = auto_start_raw.strip().lower() not in ('0', 'false', 'no', 'off')

    title = upload_fields.get('title') or original_name or 'Seedr torrent'

    result = await seedr_queue.add_job(
        torrent_file=saved_path,
        title=title,
        folder=folder,
        custom_name_prefix=custom_name_prefix,
        auto_start=auto_start,
        folder_id=str(folder_id),
    )

    if result.get('status') == 'error':
        try:
            os.remove(saved_path)
        except OSError:
            pass

    return web.Response(text=serializer.encode(result))



@routes.post(config.URL_PREFIX + 'proxy/probe')
async def proxy_probe(request):
    try:
        post = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(text='Invalid JSON payload')

    url = post.get('url')
    if not url:
        raise web.HTTPBadRequest(text='Missing url parameter')

    _session, user_id, _ = await get_user_context(request)
    proxy_queue = await download_manager.get_proxy_queue(user_id)
    result = await proxy_queue.probe(url)
    return web.json_response(result)


@routes.post(config.URL_PREFIX + 'proxy/add')
async def proxy_add(request):
    try:
        post = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(text='Invalid JSON payload')

    url = post.get('url')
    if not url:
        raise web.HTTPBadRequest(text='Missing url parameter')

    title = post.get('title')
    folder = post.get('folder') or ''
    custom_name_prefix = post.get('custom_name_prefix') or ''
    auto_start = bool(post.get('auto_start', True))
    size_limit_mb = post.get('size_limit_mb')
    size_limit_override = None
    if size_limit_mb is not None:
        try:
            size_limit_override = max(int(size_limit_mb), 0) * 1024 * 1024
        except (TypeError, ValueError):
            raise web.HTTPBadRequest(text='Invalid size_limit_mb value')

    _session, user_id, _ = await get_user_context(request)
    proxy_queue = await download_manager.get_proxy_queue(user_id)
    result = await proxy_queue.add_job(
        url=url,
        title=title,
        folder=folder,
        custom_name_prefix=custom_name_prefix,
        size_limit_override=size_limit_override,
        auto_start=auto_start
    )
    return web.json_response(result)


@routes.post(config.URL_PREFIX + 'gallerydl/add')
async def gallerydl_add(request):
    try:
        post = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(text='Invalid JSON payload')

    url = post.get('url')
    if not url:
        raise web.HTTPBadRequest(text='Missing url parameter')

    title = post.get('title') or ''
    auto_start = bool(post.get('auto_start', True))
    options = post.get('options') or []
    if not isinstance(options, list):
        raise web.HTTPBadRequest(text='options must be an array')
    sanitized_options = []
    for option in options:
        if not isinstance(option, str):
            raise web.HTTPBadRequest(text='options must contain only strings')
        value = option.strip()
        if not value:
            continue
        if len(value) > 200:
            value = value[:200]
        sanitized_options.append(value)
        if len(sanitized_options) >= 64:
            break

    def _parse_optional_string(field: str, max_length: int = 200) -> Optional[str]:
        value = post.get(field)
        if value is None:
            return None
        if isinstance(value, (int, float)):
            value = str(value)
        if not isinstance(value, str):
            raise web.HTTPBadRequest(text=f'{field} must be a string')
        text = value.strip()
        if not text:
            return None
        if len(text) > max_length:
            text = text[:max_length]
        return text

    def _parse_bool(field: str) -> bool:
        value = post.get(field)
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            lowered = value.strip().lower()
            return lowered in ('1', 'true', 'yes', 'on')
        return False

    credential_id_raw = post.get('credential_id')
    if credential_id_raw is not None and not isinstance(credential_id_raw, str):
        raise web.HTTPBadRequest(text='credential_id must be a string')
    credential_id = credential_id_raw.strip() if isinstance(credential_id_raw, str) else None
    if credential_id:
        if len(credential_id) > 120:
            raise web.HTTPBadRequest(text='credential_id is too long')
    else:
        credential_id = None

    cookie_name_raw = post.get('cookie_name')
    if cookie_name_raw is not None and not isinstance(cookie_name_raw, str):
        raise web.HTTPBadRequest(text='cookie_name must be a string')
    cookie_name = cookie_name_raw.strip() if isinstance(cookie_name_raw, str) else None
    if cookie_name == '':
        cookie_name = None

    proxy_value = _parse_optional_string('proxy', 200)

    retries_value = post.get('retries')
    if retries_value is None:
        retries = None
    else:
        try:
            retries = max(int(retries_value), 0)
        except (TypeError, ValueError):
            raise web.HTTPBadRequest(text='retries must be an integer')
        if retries > 20:
            retries = 20

    sleep_request = _parse_optional_string('sleep_request', 50)
    sleep_429 = _parse_optional_string('sleep_429', 50)

    write_metadata = _parse_bool('write_metadata')
    write_info_json = _parse_bool('write_info_json')
    write_tags = _parse_bool('write_tags')
    download_archive = _parse_bool('download_archive')

    archive_id_raw = post.get('archive_id')
    if archive_id_raw is not None and not isinstance(archive_id_raw, str):
        raise web.HTTPBadRequest(text='archive_id must be a string')
    archive_id = archive_id_raw.strip() if isinstance(archive_id_raw, str) else None
    if archive_id:
        if len(archive_id) > 120:
            raise web.HTTPBadRequest(text='archive_id is too long')
        if not all(ch.isalnum() or ch in ('-', '_', '.') for ch in archive_id):
            raise web.HTTPBadRequest(text='archive_id contains invalid characters')
    else:
        archive_id = None
    if download_archive and archive_id is None:
        archive_id = None

    _session, user_id, _ = await get_user_context(request)
    credential_store = get_gallery_credential_store(user_id)
    cookie_store = get_gallery_cookie_store(user_id)

    if credential_id and not credential_store.get_credential(credential_id):
        raise web.HTTPBadRequest(text='Credential profile not found')

    if cookie_name:
        try:
            cookie_path = cookie_store.resolve_path(cookie_name)
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc))
        if not os.path.exists(cookie_path):
            raise web.HTTPBadRequest(text='Cookie file not found')

    gallery_queue = await download_manager.get_gallery_queue(user_id)
    result = await gallery_queue.add_job(
        url=url,
        title=title,
        auto_start=auto_start,
        options=sanitized_options,
        credential_id=credential_id,
        cookie_name=cookie_name,
        proxy=proxy_value,
        retries=retries,
        sleep_request=sleep_request,
        sleep429=sleep_429,
        write_metadata=write_metadata,
        write_info_json=write_info_json,
        write_tags=write_tags,
        download_archive=download_archive,
        archive_id=archive_id,
    )
    return web.Response(text=serializer.encode(result))


@routes.get(config.URL_PREFIX + 'gallerydl/credentials')
async def gallerydl_list_credentials(request):
    _session, user_id = await require_user_session(request)
    store = get_gallery_credential_store(user_id)
    records = store.list_credentials()
    return web.json_response({'status': 'ok', 'credentials': records})


@routes.post(config.URL_PREFIX + 'gallerydl/credentials')
async def gallerydl_create_credential(request):
    _session, user_id = await require_user_session(request)
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(text='Invalid JSON payload')

    name = (payload.get('name') or '').strip()
    extractor = (payload.get('extractor') or '').strip() or None
    username = (payload.get('username') or '').strip() or None
    password = payload.get('password')
    twofactor = (payload.get('twofactor') or '').strip() or None
    extra_args = payload.get('extra_args') or []
    if not name:
        raise web.HTTPBadRequest(text='name is required')
    if password is not None and not isinstance(password, str):
        raise web.HTTPBadRequest(text='password must be a string')
    if not isinstance(extra_args, list):
        raise web.HTTPBadRequest(text='extra_args must be an array')

    store = get_gallery_credential_store(user_id)
    record = store.create_credential(
        name=name,
        extractor=extractor,
        username=username,
        password=password,
        twofactor=twofactor,
        extra_args=extra_args,
    )
    return web.json_response({'status': 'ok', 'credential': record})


@routes.get(config.URL_PREFIX + 'gallerydl/credentials/{credential_id}')
async def gallerydl_get_credential(request):
    _session, user_id = await require_user_session(request)
    credential_id = request.match_info.get('credential_id')
    store = get_gallery_credential_store(user_id)
    record = store.get_credential(credential_id)
    if not record:
        raise web.HTTPNotFound(text='Credential not found')
    values = dict(record.get('values') or {})
    has_password = bool(values.get('password'))
    values.pop('password', None)
    record.pop('values', None)
    record['values'] = values
    record['has_password'] = has_password
    return web.json_response({'status': 'ok', 'credential': record})


@routes.patch(config.URL_PREFIX + 'gallerydl/credentials/{credential_id}')
async def gallerydl_update_credential(request):
    _session, user_id = await require_user_session(request)
    credential_id = request.match_info.get('credential_id')
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(text='Invalid JSON payload')

    extra_args = payload.get('extra_args') if 'extra_args' in payload else None
    if extra_args is not None and not isinstance(extra_args, list):
        raise web.HTTPBadRequest(text='extra_args must be an array')
    password = payload.get('password') if 'password' in payload else None
    if password is not None and not isinstance(password, str):
        raise web.HTTPBadRequest(text='password must be a string')
    store = get_gallery_credential_store(user_id)
    try:
        record = store.update_credential(
            credential_id,
            name=payload.get('name'),
            extractor=payload.get('extractor'),
            username=payload.get('username'),
            password=password,
            twofactor=payload.get('twofactor'),
            extra_args=extra_args,
        )
    except KeyError:
        raise web.HTTPNotFound(text='Credential not found')
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc))
    return web.json_response({'status': 'ok', 'credential': record})


@routes.delete(config.URL_PREFIX + 'gallerydl/credentials/{credential_id}')
async def gallerydl_delete_credential(request):
    _session, user_id = await require_user_session(request)
    credential_id = request.match_info.get('credential_id')
    store = get_gallery_credential_store(user_id)
    try:
        store.delete_credential(credential_id)
    except KeyError:
        raise web.HTTPNotFound(text='Credential not found')
    return web.json_response({'status': 'ok'})


@routes.get(config.URL_PREFIX + 'gallerydl/cookies')
async def gallerydl_list_cookies(request):
    _session, user_id = await require_user_session(request)
    store = get_gallery_cookie_store(user_id)
    cookies = store.list_cookies()
    return web.json_response({'status': 'ok', 'cookies': cookies})


@routes.post(config.URL_PREFIX + 'gallerydl/cookies')
async def gallerydl_save_cookie(request):
    _session, user_id = await require_user_session(request)
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(text='Invalid JSON payload')

    name = payload.get('name')
    content = payload.get('content')
    if not isinstance(name, str) or not name.strip():
        raise web.HTTPBadRequest(text='name is required')
    if not isinstance(content, str) or not content.strip():
        raise web.HTTPBadRequest(text='content is required')
    if len(content) > 1024 * 1024:
        raise web.HTTPRequestEntityTooLarge()

    try:
        store = get_gallery_cookie_store(user_id)
        record = store.save_cookie(name, content.rstrip('\n') + '\n')
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc))
    return web.json_response({'status': 'ok', 'cookie': record})


@routes.get(config.URL_PREFIX + 'gallerydl/cookies/{name}')
async def gallerydl_get_cookie(request):
    _session, user_id = await require_user_session(request)
    name = request.match_info.get('name')
    store = get_gallery_cookie_store(user_id)
    try:
        content = store.read_cookie(name)
    except (ValueError, FileNotFoundError):
        raise web.HTTPNotFound(text='Cookie not found')
    return web.json_response({'status': 'ok', 'name': name, 'content': content})


@routes.delete(config.URL_PREFIX + 'gallerydl/cookies/{name}')
async def gallerydl_delete_cookie(request):
    _session, user_id = await require_user_session(request)
    name = request.match_info.get('name')
    store = get_gallery_cookie_store(user_id)
    try:
        store.delete_cookie(name)
    except (ValueError, FileNotFoundError):
        raise web.HTTPNotFound(text='Cookie not found')
    return web.json_response({'status': 'ok'})


@routes.get(config.URL_PREFIX + 'supported-sites')
async def supported_sites(request):
    _session, user_id, _ = await get_user_context(request)
    providers = {
        'ytdlp': list_ytdlp_sites(),
        'gallerydl': list_gallerydl_sites(getattr(config, 'GALLERY_DL_EXEC', 'gallery-dl')),
        'hqporner': ['hqporner'],
        'proxy': ['direct-link'],
        'seedr': ['seedr'],
    }
    return web.json_response({'status': 'ok', 'providers': providers})


@routes.get(config.URL_PREFIX + 'cookies')
async def get_cookies(request):
    session = await get_session(request)
    user_id = session.get('user_id')
    if not user_id:
        raise web.HTTPUnauthorized()
    store = get_ytdlp_cookie_store(user_id)
    profiles = store.list_profiles()

    legacy_cookie_path = session.get('cookie_file')
    if legacy_cookie_path:
        user_dir = ensure_cookie_directory(user_id)
        if not legacy_cookie_path.startswith(user_dir) or not os.path.exists(legacy_cookie_path):
            legacy_cookie_path = None
            session.pop('cookie_file', None)

    if not profiles and legacy_cookie_path:
        try:
            with open(legacy_cookie_path, 'r', encoding='utf-8') as fh:
                legacy_content = fh.read()
            entry = store.save_profile(
                name='Imported YouTube cookies',
                cookies=legacy_content,
                hosts=DEFAULT_YTDLP_HOSTS,
                default=True,
            )
            session['cookie_file'] = store.resolve_profile_path(entry['id'])
            profiles = store.list_profiles()
        except (OSError, ValueError, KeyError) as exc:
            log.warning('Failed to migrate legacy cookie file: %s', exc)

    has_cookies = bool(profiles)
    state = cookie_status_store.sync_presence(user_id, has_cookies)
    state['profile_count'] = len(profiles)
    default_profile = next((profile for profile in profiles if profile.get('default')), None)
    if default_profile:
        state['default_profile_id'] = default_profile.get('id')
    return web.json_response(state)


@routes.get(config.URL_PREFIX + 'ytdlp/cookies')
async def ytdlp_list_cookies(request):
    session = await get_session(request)
    user_id = session.get('user_id')
    if not user_id:
        raise web.HTTPUnauthorized()
    store = get_ytdlp_cookie_store(user_id)
    profiles = store.list_profiles()
    return web.json_response({'status': 'ok', 'profiles': profiles})


@routes.post(config.URL_PREFIX + 'cookies')
async def set_cookies(request):
    try:
        post = await request.json()
    except json.JSONDecodeError:
        log.error("Failed to decode cookies payload")
        raise web.HTTPBadRequest()

    session = await get_session(request)
    user_id = session.get('user_id')
    if not user_id:
        raise web.HTTPUnauthorized()
    store = get_ytdlp_cookie_store(user_id)
    profile_id = post.get('profile_id') if isinstance(post.get('profile_id'), str) else None

    cookie_payload = post.get('cookies')
    if profile_id and cookie_payload is None:
        cookie_text = None
    else:
        if not cookie_payload or not isinstance(cookie_payload, str):
            log.error("Bad request: missing 'cookies' payload")
            raise web.HTTPBadRequest()
        if len(cookie_payload) > 1024 * 1024:
            log.warning("Cookie payload too large")
            raise web.HTTPRequestEntityTooLarge()
        cookie_text = cookie_payload

    if profile_id is None and cookie_text is None:
        raise web.HTTPBadRequest(text='Cookie data is required when creating a new profile')

    name = (post.get('name') or '').strip() or 'YouTube cookies'
    hosts = _parse_string_list(post.get('hosts')) or DEFAULT_YTDLP_HOSTS
    tags = _parse_string_list(post.get('tags'))
    default_flag = _coerce_bool(post.get('default'))

    if not tags and any(host in {'youtube.com', 'youtu.be'} for host in hosts):
        tags = ['youtube']

    try:
        record = store.save_profile(
            name=name,
            cookies=cookie_text,
            tags=tags,
            hosts=hosts,
            default=default_flag or not store.list_profiles(),
            profile_id=profile_id,
        )
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc))
    except KeyError:
        raise web.HTTPNotFound(text='Cookie profile not found')
    except OSError as exc:
        log.error(f"Failed to persist cookie profile: {exc!r}")
        raise web.HTTPInternalServerError(text='Failed to persist cookies')

    state = cookie_status_store.mark_unknown(user_id)
    profiles = store.list_profiles()
    state['profile_count'] = len(profiles)
    default_profile = next((profile for profile in profiles if profile.get('default')), None)
    if default_profile:
        state['default_profile_id'] = default_profile.get('id')

    selected_profile = default_profile or next((profile for profile in profiles if profile.get('id') == record['id']), None)
    if selected_profile:
        path_for_session = store.resolve_profile_path(selected_profile['id'])
        if path_for_session:
            session['cookie_file'] = path_for_session
        else:
            session.pop('cookie_file', None)
    else:
        session.pop('cookie_file', None)

    return web.json_response({'status': 'ok', 'cookies': state, 'profile': record})


@routes.delete(config.URL_PREFIX + 'cookies')
async def clear_cookies(request):
    session = await get_session(request)
    user_id = session.get('user_id')
    if not user_id:
        raise web.HTTPUnauthorized()
    profile_id = request.rel_url.query.get('profile_id')
    store = get_ytdlp_cookie_store(user_id)

    try:
        if profile_id:
            store.delete_profile(profile_id)
        else:
            for profile in list(store.list_profiles()):
                with suppress(KeyError):
                    store.delete_profile(profile['id'])
    except KeyError:
        raise web.HTTPNotFound(text='Cookie profile not found')
    except OSError as exc:
        log.error(f"Failed to delete cookie profile: {exc!r}")
        raise web.HTTPInternalServerError(text='Failed to remove cookies')

    remaining = store.list_profiles()
    state = cookie_status_store.sync_presence(user_id, bool(remaining)) if remaining else cookie_status_store.clear(user_id)
    state['profile_count'] = len(remaining)
    default_profile = next((profile for profile in remaining if profile.get('default')), None)
    if default_profile:
        state['default_profile_id'] = default_profile.get('id')

    if default_profile:
        path_for_session = store.resolve_profile_path(default_profile['id'])
        if path_for_session:
            session['cookie_file'] = path_for_session
        else:
            session.pop('cookie_file', None)
    else:
        session.pop('cookie_file', None)

    return web.json_response({'status': 'ok', 'cookies': state})


@routes.get(config.URL_PREFIX + 'me')
async def current_user(request):
    session = await get_session(request)
    if not session.get('authenticated'):
        raise web.HTTPUnauthorized()
    return web.json_response({
        'id': session.get('user_id'),
        'username': session.get('username'),
        'role': session.get('role')
    })


@routes.get(config.URL_PREFIX + 'admin/users')
async def admin_list_users(request):
    session = await get_session(request)
    ensure_admin(session)
    users = user_store.list_users()
    return web.json_response({'users': users})


@routes.post(config.URL_PREFIX + 'admin/users')
async def admin_create_user(request):
    session = await get_session(request)
    ensure_admin(session)
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(text='Invalid JSON payload')

    username = (payload.get('username') or '').strip()
    password = payload.get('password') or ''
    role = payload.get('role') or 'user'

    if not username or not password:
        raise web.HTTPBadRequest(text='Username and password are required')

    try:
        user = user_store.create_user(username, password, role=role)
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc))

    return web.json_response(user, status=201)


@routes.patch(config.URL_PREFIX + 'admin/users/{user_id}')
async def admin_update_user(request):
    session = await get_session(request)
    ensure_admin(session)
    user_id = request.match_info['user_id']

    try:
        payload = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(text='Invalid JSON payload')

    user = user_store.get_user_by_id(user_id)
    if not user:
        raise web.HTTPNotFound(text='User not found')

    password_updated = False

    if 'password' in payload and payload['password']:
        user_store.set_password(user_id, payload['password'])
        password_updated = True

    if 'role' in payload and payload['role']:
        new_role = payload['role']
        if new_role not in ('admin', 'user'):
            raise web.HTTPBadRequest(text='Invalid role')
        if new_role != 'admin' and not _has_other_active_admins(exclude_id=user_id):
            raise web.HTTPConflict(text='Cannot remove the last active admin')
        user_store.set_role(user_id, new_role)

    if 'disabled' in payload:
        disabled = bool(payload['disabled'])
        if disabled and not _has_other_active_admins(exclude_id=user_id):
            raise web.HTTPConflict(text='Cannot disable the last active admin')
        user_store.set_disabled(user_id, disabled)

    updated_user = user_store.get_user_by_id(user_id)
    sanitized = updated_user.copy()
    sanitized.pop('password_hash', None)
    if password_updated:
        sanitized['password_updated'] = True
    return web.json_response(sanitized)


@routes.delete(config.URL_PREFIX + 'admin/users/{user_id}')
async def admin_delete_user(request):
    session = await get_session(request)
    ensure_admin(session)
    user_id = request.match_info['user_id']

    user = user_store.get_user_by_id(user_id)
    if not user:
        raise web.HTTPNotFound(text='User not found')

    if user.get('role') == 'admin' and not _has_other_active_admins(exclude_id=user_id):
        raise web.HTTPConflict(text='Cannot delete the last active admin')

    user_store.delete_user(user_id)
    return web.json_response({'status': 'deleted'})


@routes.get(config.URL_PREFIX + 'admin/proxy-settings')
async def admin_get_proxy_settings(request):
    session = await get_session(request)
    ensure_admin(session)
    data = await proxy_settings.get()
    return web.json_response({
        'limit_enabled': bool(data.get('limit_enabled', False)),
        'limit_mb': int(data.get('limit_mb', 0))
    })


@routes.post(config.URL_PREFIX + 'admin/proxy-settings')
async def admin_set_proxy_settings(request):
    session = await get_session(request)
    ensure_admin(session)

    try:
        payload = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(text='Invalid JSON payload')

    limit_enabled = payload.get('limit_enabled')
    limit_mb = payload.get('limit_mb')

    updates = {}
    if limit_enabled is not None:
        if not isinstance(limit_enabled, bool):
            raise web.HTTPBadRequest(text='limit_enabled must be a boolean')
        updates['limit_enabled'] = limit_enabled

    if limit_mb is not None:
        try:
            limit_mb_int = max(int(limit_mb), 0)
        except (TypeError, ValueError):
            raise web.HTTPBadRequest(text='limit_mb must be a non-negative integer')
        updates['limit_mb'] = limit_mb_int

    if updates:
        await proxy_settings.update(**updates)

    data = await proxy_settings.get()
    return web.json_response({
        'limit_enabled': bool(data.get('limit_enabled', False)),
        'limit_mb': int(data.get('limit_mb', 0))
    })


@routes.get(config.URL_PREFIX + 'admin/system-stats')
async def admin_system_stats(request):
    session = await get_session(request)
    ensure_admin(session)

    cpu_percent = await asyncio.to_thread(psutil.cpu_percent, interval=0.1)
    memory = psutil.virtual_memory()
    swap = psutil.swap_memory()
    net = psutil.net_io_counters()
    now = time.time()
    uptime_seconds = max(now - psutil.boot_time(), 0.0)

    payload = {
        'cpu': {
            'percent': cpu_percent,
            'cores': psutil.cpu_count(logical=False) or psutil.cpu_count(logical=True) or 1,
            'threads': psutil.cpu_count() or 1,
        },
        'memory': {
            'percent': memory.percent,
            'used': memory.used,
            'available': memory.available,
            'total': memory.total,
        },
        'swap': {
            'percent': swap.percent,
            'used': swap.used,
            'total': swap.total,
        },
        'network': {
            'bytes_sent': net.bytes_sent,
            'bytes_recv': net.bytes_recv,
        },
        'uptime_seconds': uptime_seconds,
        'timestamp': now,
    }

    return web.json_response(payload)


@routes.get(config.URL_PREFIX + 'history')
async def history(request):
    session, user_id, queue = await get_user_context(request)
    proxy_queue = await download_manager.get_proxy_queue(user_id)
    gallery_queue = await download_manager.get_gallery_queue(user_id)

    try:
        limit = int(request.query.get('limit', download_manager.max_history_items))
    except (TypeError, ValueError):
        limit = download_manager.max_history_items
    try:
        offset = int(request.query.get('offset', 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(0, limit)
    offset = max(0, offset)

    history = {
        'done': [],
        'queue': [],
        'pending': [],
        'proxy_done': [],
        'gallery_done': [],
        'seedr_done': [],
        'limit': limit,
        'offset': offset,
    }

    for _, v in queue.queue.saved_items():
        history['queue'].append(v)
    for _, v in queue.pending.saved_items():
        history['pending'].append(v)

    done_items = list(queue.done.saved_items())
    proxy_done = [(key, job.info) for key, job in proxy_queue.done.items()]
    gallery_done = [(key, job.info) for key, job in gallery_queue.done.items()]
    seedr_done = [(key, job.info) for key, job in seedr_queue.done.items()]

    def collect_slice(items):
        ordered = sorted(items, key=lambda item: getattr(item[1], 'timestamp', 0), reverse=True)
        total = len(ordered)
        if limit > 0:
            sliced = ordered[offset: offset + limit]
        else:
            sliced = ordered[offset:]
        return total, [info for _, info in sliced]

    total_done, history['done'] = collect_slice(done_items)
    total_proxy_done, history['proxy_done'] = collect_slice(proxy_done)
    total_gallery_done, history['gallery_done'] = collect_slice(gallery_done)
    total_seedr_done, history['seedr_done'] = collect_slice(seedr_done)

    history['done_total'] = total_done
    history['proxy_done_total'] = total_proxy_done
    history['gallery_done_total'] = total_gallery_done
    history['seedr_done_total'] = total_seedr_done

    log.info("Sending download history slice offset=%s limit=%s", offset, limit)
    return web.Response(text=serializer.encode(history))


@routes.get(config.URL_PREFIX + 'stream')
async def stream_download(request):
    _session, user_id, _ = await get_user_context(request)
    download_id = request.query.get('id')
    if not download_id:
        raise web.HTTPBadRequest(text='Missing id parameter')

    target = await resolve_stream_target(user_id, download_id)
    file_path = target.file_path
    base_directory = target.base_directory

    try:
        if os.path.commonpath([file_path, base_directory]) != base_directory:
            raise web.HTTPForbidden(text='Invalid file path')
    except ValueError:
        raise web.HTTPForbidden(text='Invalid file path')

    if not os.path.isfile(file_path):
        raise web.HTTPNotFound(text='File not found')

    mime_type, _ = mimetypes.guess_type(file_path)
    file_size = os.path.getsize(file_path)
    range_header = request.headers.get('Range')

    if range_header:
        match = re.match(r'bytes=(\d*)-(\d*)$', range_header.strip())
        if not match:
            raise web.HTTPRequestRangeNotSatisfiable(headers={'Content-Range': f'bytes */{file_size}'})

        start_str, end_str = match.groups()
        is_suffix_request = False

        if start_str:
            start = int(start_str)
            if start >= file_size:
                raise web.HTTPRequestRangeNotSatisfiable(headers={'Content-Range': f'bytes */{file_size}'})
        elif end_str:
            suffix = int(end_str)
            if suffix <= 0:
                raise web.HTTPRequestRangeNotSatisfiable(headers={'Content-Range': f'bytes */{file_size}'})
            start = max(file_size - suffix, 0)
            is_suffix_request = True
        else:
            start = 0

        if end_str and not is_suffix_request:
            requested_end = int(end_str)
        else:
            requested_end = file_size - 1

        if requested_end < start:
            raise web.HTTPRequestRangeNotSatisfiable(headers={'Content-Range': f'bytes */{file_size}'})

        end = min(requested_end, file_size - 1)
        if end_str and not is_suffix_request and end - start + 1 > MAX_STREAM_CHUNK:
            end = min(start + MAX_STREAM_CHUNK - 1, file_size - 1)

        chunk_length = end - start + 1
        headers = {
            'Content-Disposition': f'inline; filename="{os.path.basename(file_path)}"',
            'Content-Range': f'bytes {start}-{end}/{file_size}',
            'Content-Length': str(chunk_length),
            'Accept-Ranges': 'bytes',
        }

        if request.method == 'HEAD':
            response = web.Response(status=206, headers=headers)
            response.content_type = mime_type or 'application/octet-stream'
            return response

        response = web.StreamResponse(status=206, headers=headers)
        response.content_type = mime_type or 'application/octet-stream'
        try:
            await response.prepare(request)
        except (ClientConnectionResetError, ConnectionResetError, ConnectionError):
            log.debug('Client disconnected before stream preparation', exc_info=True)
            return response

        chunk_size = 256 * 1024
        with open(file_path, 'rb') as fh:
            fh.seek(start)
            remaining = chunk_length
            while remaining > 0:
                read_size = min(chunk_size, remaining)
                data = await asyncio.to_thread(fh.read, read_size)
                if not data:
                    break
                remaining -= len(data)
                try:
                    await response.write(data)
                except (ClientConnectionResetError, ConnectionResetError, ConnectionError):
                    log.debug('Client disconnected during stream', exc_info=True)
                    break

        with suppress(ClientConnectionResetError, ConnectionResetError, ConnectionError):
            await response.write_eof()
        return response

    headers = {
        'Content-Disposition': f'inline; filename="{os.path.basename(file_path)}"',
        'Accept-Ranges': 'bytes',
        'Content-Length': str(file_size),
    }

    if request.method == 'HEAD':
        response = web.Response(status=200, headers=headers)
        response.content_type = mime_type or 'application/octet-stream'
        return response

    response = web.FileResponse(path=file_path, headers=headers)
    response.content_type = mime_type or 'application/octet-stream'
    return response


@routes.get(config.URL_PREFIX + 'stream/hls/{token}/index.m3u8')
async def stream_hls_playlist(request):
    _session, user_id = await require_user_session(request)
    token = request.match_info.get('token', '')
    download_id = _decode_stream_token(token)
    target = await resolve_stream_target(user_id, download_id)

    try:
        session = await stream_hls_manager.ensure_session(user_id, download_id, target.file_path)
    except HlsUnavailableError as exc:
        status_changed = refresh_stream_transcode_status()
        if status_changed:
            await sio.emit('configuration', serializer.encode(config), room=f'user:{user_id}')
        message = str(exc) or 'Adaptive streaming is not available'
        log.info(
            'Adaptive streaming unavailable (playlist): user=%s download=%s reason=%s',
            user_id,
            download_id,
            message,
        )
        raise web.HTTPNotFound(text=message)
    except HlsGenerationError as exc:
        log.error(
            'Adaptive streaming failed during generation (playlist): user=%s download=%s error=%s',
            user_id,
            download_id,
            exc,
        )
        raise web.HTTPInternalServerError(text=str(exc))

    headers = {
        'Cache-Control': 'no-cache, no-store, must-revalidate',
    }
    log.info(
        'Adaptive streaming playlist ready: user=%s download=%s manifest=%s',
        user_id,
        download_id,
        session.playlist_path,
    )
    response = web.FileResponse(session.playlist_path, headers=headers)
    response.content_type = 'application/vnd.apple.mpegurl'
    return response


@routes.get(config.URL_PREFIX + 'stream/hls/{token}/{segment}')
async def stream_hls_segment(request):
    _session, user_id = await require_user_session(request)
    token = request.match_info.get('token', '')
    segment_name = _sanitize_segment_name(request.match_info.get('segment', ''))
    download_id = _decode_stream_token(token)
    target = await resolve_stream_target(user_id, download_id)

    directory = stream_hls_manager.session_directory(user_id, download_id)
    segment_path = os.path.join(directory, segment_name)

    if not os.path.exists(segment_path):
        try:
            session = await stream_hls_manager.ensure_session(user_id, download_id, target.file_path)
        except HlsUnavailableError as exc:
            status_changed = refresh_stream_transcode_status()
            if status_changed:
                await sio.emit('configuration', serializer.encode(config), room=f'user:{user_id}')
            message = str(exc) or 'Adaptive streaming is not available'
            log.info(
                'Adaptive streaming unavailable (segment): user=%s download=%s segment=%s reason=%s',
                user_id,
                download_id,
                segment_name,
                message,
            )
            raise web.HTTPNotFound(text=message)
        except HlsGenerationError as exc:
            log.error(
                'Adaptive streaming failed during generation (segment): user=%s download=%s segment=%s error=%s',
                user_id,
                download_id,
                segment_name,
                exc,
            )
            raise web.HTTPInternalServerError(text=str(exc))
        segment_path = os.path.join(session.directory, segment_name)
        if not os.path.exists(segment_path):
            raise web.HTTPNotFound(text='Segment not found')

    stream_hls_manager.touch_session(user_id, download_id)

    headers = {
        'Cache-Control': 'no-cache, no-store, must-revalidate',
    }
    response = web.FileResponse(segment_path, headers=headers)
    response.content_type = 'video/mp2t'
    return response

@sio.event
async def connect(sid, environ):
    request = environ.get('aiohttp.request')
    if request is None:
        log.warning("Socket connect without request context; disconnecting")
        await sio.disconnect(sid)
        return

    session = await get_session(request)
    user_id = session.get('user_id')
    username = session.get('username')
    if not user_id:
        log.warning("Socket connect without authenticated session; disconnecting")
        await sio.disconnect(sid)
        return

    log.info(f"Client connected: {sid} (user={username})")
    room = f'user:{user_id}'
    await sio.enter_room(sid, room)

    queue_state = await download_manager.get_combined_state(user_id)
    await sio.emit('all', serializer.encode(queue_state), to=sid)
    await sio.emit('configuration', serializer.encode(config), to=sid)
    if config.CUSTOM_DIRS:
        await sio.emit('custom_dirs', serializer.encode(get_custom_dirs()), to=sid)
    if config.YTDL_OPTIONS_FILE:
        await sio.emit('ytdl_options_changed', serializer.encode(get_options_update_time()), to=sid)

def get_custom_dirs():
    def recursive_dirs(base):
        path = pathlib.Path(base)

        # Converts PosixPath object to string, and remove base/ prefix
        def convert(p):
            s = str(p)
            if s.startswith(base):
                s = s[len(base):]

            if s.startswith('/'):
                s = s[1:]

            return s

        # Include only directories which do not match the exclude filter
        def include_dir(d):
            if len(config.CUSTOM_DIRS_EXCLUDE_REGEX) == 0:
                return True
            else:
                return re.search(config.CUSTOM_DIRS_EXCLUDE_REGEX, d) is None

        # Recursively lists all subdirectories of DOWNLOAD_DIR
        dirs = list(filter(include_dir, map(convert, path.glob('**/'))))

        return dirs

    download_dir = recursive_dirs(config.DOWNLOAD_DIR)

    audio_download_dir = download_dir
    if config.DOWNLOAD_DIR != config.AUDIO_DOWNLOAD_DIR:
        audio_download_dir = recursive_dirs(config.AUDIO_DOWNLOAD_DIR)

    return {
        "download_dir": download_dir,
        "audio_download_dir": audio_download_dir
    }

@routes.get(config.URL_PREFIX)
def index(request):
    response = web.FileResponse(os.path.join(config.BASE_DIR, 'ui/dist/metube/browser/index.html'))
    if 'metube_theme' not in request.cookies:
        response.set_cookie('metube_theme', config.DEFAULT_THEME)
    return response

@routes.get(config.URL_PREFIX + 'robots.txt')
def robots(request):
    if config.ROBOTS_TXT:
        response = web.FileResponse(os.path.join(config.BASE_DIR, config.ROBOTS_TXT))
    else:
        response = web.Response(
            text="User-agent: *\nDisallow: /download/\nDisallow: /audio_download/\n"
        )
    return response

@routes.get(config.URL_PREFIX + 'version')
def version(request):
    payload = {
        "yt-dlp": yt_dlp_version,
        "version": os.getenv("METUBE_VERSION", "dev"),
    }
    if gallery_dl_version:
        payload["gallery-dl"] = gallery_dl_version
    return web.json_response(payload)

if config.URL_PREFIX != '/':
    @routes.get('/')
    def index_redirect_root(request):
        return web.HTTPFound(config.URL_PREFIX)

    @routes.get(config.URL_PREFIX[:-1])
    def index_redirect_dir(request):
        return web.HTTPFound(config.URL_PREFIX)

routes.static(config.URL_PREFIX + 'download/', config.DOWNLOAD_DIR, show_index=config.DOWNLOAD_DIRS_INDEXABLE)
routes.static(config.URL_PREFIX + 'audio_download/', config.AUDIO_DOWNLOAD_DIR, show_index=config.DOWNLOAD_DIRS_INDEXABLE)
routes.static(config.URL_PREFIX, os.path.join(config.BASE_DIR, 'ui/dist/metube/browser'))
try:
    app.add_routes(routes)
except ValueError as e:
    if 'ui/dist/metube/browser' in str(e):
        raise RuntimeError('Could not find the frontend UI static assets. Please run `node_modules/.bin/ng build` inside the ui folder') from e
    raise e

# https://github.com/aio-libs/aiohttp/pull/4615 waiting for release
# @routes.options(config.URL_PREFIX + 'add')
async def add_cors(request):
    return web.Response(text=serializer.encode({"status": "ok"}))

app.router.add_route('OPTIONS', config.URL_PREFIX + 'add', add_cors)

async def on_prepare(request, response):
    if 'Origin' in request.headers:
        response.headers['Access-Control-Allow-Origin'] = request.headers['Origin']
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'

app.on_response_prepare.append(on_prepare)

def supports_reuse_port():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        sock.close()
        return True
    except (AttributeError, OSError):
        return False

def parseLogLevel(logLevel):
    match logLevel:
        case 'DEBUG':
            return logging.DEBUG
        case 'INFO':
            return logging.INFO
        case 'WARNING':
            return logging.WARNING
        case 'ERROR':
            return logging.ERROR
        case 'CRITICAL':
            return logging.CRITICAL
        case _:
            return None

def isAccessLogEnabled():
    if config.ENABLE_ACCESSLOG:
        return access_logger
    else:
        return None

if __name__ == '__main__':
    logging.basicConfig(level=parseLogLevel(config.LOGLEVEL))
    log.info(f"Listening on {config.HOST}:{config.PORT}")

    setup_auth(app, sio, config, user_store)

    if config.HTTPS:
        ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_context.load_cert_chain(certfile=config.CERTFILE, keyfile=config.KEYFILE)
        web.run_app(app, host=config.HOST, port=int(config.PORT), reuse_port=supports_reuse_port(), ssl_context=ssl_context, access_log=isAccessLogEnabled())
    else:
        web.run_app(app, host=config.HOST, port=int(config.PORT), reuse_port=supports_reuse_port(), access_log=isAccessLogEnabled())
#!/usr/bin/env python3
# pylint: disable=no-member,method-hidden

import os
import sys
import asyncio
import secrets
import time
import functools
from contextlib import suppress
from pathlib import Path
from typing import Any, Dict, Optional
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
from gallerydl_manager import GalleryDlManager, is_gallerydl_supported, list_gallerydl_sites
import importlib.util


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
        'GALLERY_DL_EXEC': 'gallery-dl',
    }

    _BOOLEAN = ('DOWNLOAD_DIRS_INDEXABLE', 'CUSTOM_DIRS', 'CREATE_CUSTOM_DIRS', 'DELETE_FILE_ON_TRASHCAN', 'DEFAULT_OPTION_PLAYLIST_STRICT_MODE', 'HTTPS', 'ENABLE_ACCESSLOG', 'PROXY_DOWNLOAD_LIMIT_ENABLED')

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
    def __init__(self, config, sio_server: socketio.AsyncServer, proxy_settings: ProxySettingsStore, cookie_status_store: CookieStatusStore):
        self.config = config
        self.sio = sio_server
        self._queues: Dict[str, DownloadQueue] = {}
        self._proxy_queues: Dict[str, ProxyDownloadManager] = {}
        self._gallery_queues: Dict[str, GalleryDlManager] = {}
        self._notifiers: Dict[str, UserNotifier] = {}
        self.proxy_settings = proxy_settings
        self.cookie_status_store = cookie_status_store
        self._lock = asyncio.Lock()

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
            )
            await queue.initialize()
            self._queues[user_id] = queue

            proxy_queue = ProxyDownloadManager(self.config, notifier, queue, self._state_dir_for(user_id), user_id, self.proxy_settings)
            self._proxy_queues[user_id] = proxy_queue

            gallery_queue = GalleryDlManager(
                self.config,
                notifier,
                self._state_dir_for(user_id),
                executable_path=getattr(self.config, 'GALLERY_DL_EXEC', 'gallery-dl'),
            )
            self._gallery_queues[user_id] = gallery_queue

            return queue

    async def get_proxy_queue(self, user_id: str) -> ProxyDownloadManager:
        if user_id not in self._proxy_queues:
            await self.get_queue(user_id)
        return self._proxy_queues[user_id]

    async def get_gallery_queue(self, user_id: str) -> GalleryDlManager:
        if user_id not in self._gallery_queues:
            await self.get_queue(user_id)
        return self._gallery_queues[user_id]

    async def get_combined_state(self, user_id: str):
        queue = await self.get_queue(user_id)
        proxy_queue = await self.get_proxy_queue(user_id)
        gallery_queue = await self.get_gallery_queue(user_id)
        primary_queue, primary_done = queue.get()
        proxy_queue_items, proxy_done_items = proxy_queue.get()
        gallery_queue_items, gallery_done_items = gallery_queue.get()
        return (
            primary_queue + proxy_queue_items + gallery_queue_items,
            primary_done + proxy_done_items + gallery_done_items,
        )


download_manager = DownloadManager(config, sio, proxy_settings, cookie_status_store)


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
    cookie_path = session.get('cookie_file')
    if cookie_path:
        user_cookie_dir = ensure_cookie_directory(user_id)
        if not cookie_path.startswith(user_cookie_dir) or not os.path.exists(cookie_path):
            cookie_path = None

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

    if is_gallerydl_supported(url, getattr(config, 'GALLERY_DL_EXEC', 'gallery-dl')):
        status = {
            'status': 'gallerydl',
            'gallerydl': {
                'url': url,
                'title': post.get('title') or '',
                'auto_start': auto_start,
                'options': post.get('gallerydl_options') or [],
            }
        }
    elif is_hqporner_url(url):
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
        )

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

    if where == 'queue':
        results = [
            await queue.cancel(ids),
            await proxy_queue.cancel(ids),
            await gallery_queue.cancel(ids),
        ]
        status = next((res for res in results if res.get('status') == 'error'), {'status': 'ok'})
    else:
        primary = await queue.clear(ids)
        secondary = await proxy_queue.clear(ids)
        gallery = await gallery_queue.clear(ids)
        deleted = (primary.get('deleted') or []) + (secondary.get('deleted') or []) + (gallery.get('deleted') or [])
        missing = (primary.get('missing') or []) + (secondary.get('missing') or []) + (gallery.get('missing') or [])
        status = {'status': 'ok', 'deleted': deleted, 'missing': missing}
        errors = {}
        if primary.get('status') == 'error':
            errors.update(primary.get('errors') or {})
        if secondary.get('status') == 'error':
            errors.update(secondary.get('errors') or {})
        if gallery.get('status') == 'error':
            errors.update(gallery.get('errors') or {})
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
    results = [
        await queue.start_pending(ids),
        await proxy_queue.start_jobs(ids),
        await gallery_queue.start_jobs(ids),
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
    log.info(f"Rename request processed for id: {id}")
    return web.Response(text=serializer.encode(status))


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

    _session, user_id, _ = await get_user_context(request)
    gallery_queue = await download_manager.get_gallery_queue(user_id)
    result = await gallery_queue.add_job(url=url, title=title, auto_start=auto_start, options=sanitized_options)
    return web.Response(text=serializer.encode(result))


@routes.get(config.URL_PREFIX + 'supported-sites')
async def supported_sites(request):
    _session, user_id, _ = await get_user_context(request)
    providers = {
        'ytdlp': list_ytdlp_sites(),
        'gallerydl': list_gallerydl_sites(getattr(config, 'GALLERY_DL_EXEC', 'gallery-dl')),
        'hqporner': ['hqporner'],
        'proxy': ['direct-link'],
    }
    return web.json_response({'status': 'ok', 'providers': providers})


@routes.get(config.URL_PREFIX + 'cookies')
async def get_cookies(request):
    session = await get_session(request)
    user_id = session.get('user_id')
    if not user_id:
        raise web.HTTPUnauthorized()
    cookie_path = session.get('cookie_file')
    if cookie_path:
        user_dir = ensure_cookie_directory(user_id)
        if not cookie_path.startswith(user_dir) or not os.path.exists(cookie_path):
            cookie_path = None
            session.pop('cookie_file', None)
    state = cookie_status_store.sync_presence(user_id, bool(cookie_path))
    return web.json_response(state)


@routes.post(config.URL_PREFIX + 'cookies')
async def set_cookies(request):
    try:
        post = await request.json()
    except json.JSONDecodeError:
        log.error("Failed to decode cookies payload")
        raise web.HTTPBadRequest()

    cookie_text = post.get('cookies')
    if not cookie_text or not isinstance(cookie_text, str):
        log.error("Bad request: missing 'cookies' payload")
        raise web.HTTPBadRequest()

    if len(cookie_text) > 1024 * 1024:
        log.warning("Cookie payload too large")
        raise web.HTTPRequestEntityTooLarge()

    session = await get_session(request)
    user_id = session.get('user_id')
    if not user_id:
        raise web.HTTPUnauthorized()
    cookie_path = get_cookie_path_for_session(session)

    try:
        with open(cookie_path, 'w', encoding='utf-8') as fh:
            fh.write(cookie_text.rstrip('\n') + '\n')
        try:
            os.chmod(cookie_path, 0o600)
        except PermissionError:
            log.warning(f"Unable to set permissions on cookie file {cookie_path}")
    except OSError as exc:
        log.error(f"Failed to write cookie file: {exc!r}")
        raise web.HTTPInternalServerError(text='Failed to persist cookies')

    session['cookie_file'] = cookie_path
    state = cookie_status_store.mark_unknown(user_id)

    return web.json_response({'status': 'ok', 'cookies': state})


@routes.delete(config.URL_PREFIX + 'cookies')
async def clear_cookies(request):
    session = await get_session(request)
    user_id = session.get('user_id')
    if not user_id:
        raise web.HTTPUnauthorized()
    cookie_path = session.get('cookie_file')

    if cookie_path and os.path.exists(cookie_path):
        try:
            os.remove(cookie_path)
        except OSError as exc:
            log.error(f"Failed to delete cookie file {cookie_path}: {exc!r}")
            raise web.HTTPInternalServerError(text='Failed to remove cookies')

    session.pop('cookie_file', None)
    state = cookie_status_store.clear(user_id)

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
    _session, _, queue = await get_user_context(request)
    history = {'done': [], 'queue': [], 'pending': []}

    for _, v in queue.queue.saved_items():
        history['queue'].append(v)
    for _, v in queue.done.saved_items():
        history['done'].append(v)
    for _, v in queue.pending.saved_items():
        history['pending'].append(v)

    log.info("Sending download history")
    return web.Response(text=serializer.encode(history))


@routes.get(config.URL_PREFIX + 'stream')
async def stream_download(request):
    _session, user_id, queue = await get_user_context(request)
    proxy_queue = await download_manager.get_proxy_queue(user_id)
    download_id = request.query.get('id')
    if not download_id:
        raise web.HTTPBadRequest(text='Missing id parameter')

    download = queue.done.get(download_id) if queue.done.exists(download_id) else None
    proxy_job = proxy_queue.get_done(download_id)

    if download is None and proxy_job is None:
        raise web.HTTPNotFound(text='Download not found')

    if download is not None:
        info = download.info
        if not info.filename:
            raise web.HTTPNotFound(text='File not available for streaming')
        directory = queue._resolve_download_directory(info)
        if not directory:
            raise web.HTTPNotFound(text='Download directory unavailable')
        file_path = os.path.abspath(os.path.normpath(os.path.join(directory, info.filename)))
        base_directory = os.path.abspath(directory)
    else:
        info = proxy_job.info
        file_path = proxy_job.file_path
        if not file_path:
            raise web.HTTPNotFound(text='File not available for streaming')
        file_path = os.path.abspath(os.path.normpath(file_path))
        directory = queue._resolve_download_directory(info)
        base_directory = os.path.abspath(directory or os.path.dirname(file_path))

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
    return web.json_response({
        "yt-dlp": yt_dlp_version,
        "version": os.getenv("METUBE_VERSION", "dev")
    })

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
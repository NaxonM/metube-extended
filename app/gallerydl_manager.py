import asyncio
import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import urlparse

_extractor_cache: Dict[str, Tuple[Dict[str, Optional[str]], ...]] = {}
_domain_cache: Dict[str, Tuple[str, ...]] = {}
_FILE_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".svg",
    ".webp",
    ".avif",
    ".heic",
    ".heif",
    ".mp4",
    ".m4v",
    ".mov",
    ".webm",
    ".mkv",
    ".avi",
    ".flv",
    ".ogg",
    ".mp3",
    ".wav",
    ".flac",
    ".zip",
    ".cbz",
    ".pdf",
    ".json",
    ".txt",
)

from ytdl import DownloadInfo

if TYPE_CHECKING:
    from gallerydl_credentials import CookieStore, CredentialStore

log = logging.getLogger("gallerydl")


def detect_gallerydl_version(executable: Optional[str] = None) -> Optional[str]:
    candidate = executable or os.environ.get("GALLERY_DL_EXEC") or "gallery-dl"
    try:
        completed = subprocess.run(
            [candidate, "--version"],
            capture_output=True,
            text=True,
            check=True,
        )
        output = (completed.stdout or "").strip() or (completed.stderr or "").strip()
        if not output:
            return None
        return output.splitlines()[0]
    except Exception as exc:  # pragma: no cover - clang modules not critical for runtime
        log.warning("Failed to detect gallery-dl version via %s: %s", candidate, exc)
        return None


def _sanitize_filename(value: str) -> str:
    sanitized = value.replace("\0", "").strip()
    invalid = '\\/:*?"<>|'
    for ch in invalid:
        sanitized = sanitized.replace(ch, "_")
    sanitized = sanitized.replace("..", "_")
    return sanitized or f"gallerydl-{uuid.uuid4().hex}"


def _clean_optional_str(value: Optional[str], max_length: int = 200) -> Optional[str]:
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if len(text) > max_length:
        text = text[:max_length]
    return text


def _sanitize_archive_name(value: Optional[str], fallback: str = "default") -> str:
    candidate = _clean_optional_str(value, 120) or fallback
    filtered = ''.join(ch for ch in candidate if ch.isalnum() or ch in ("-", "_", "."))
    return filtered or fallback


def _gallerydl_module_root() -> Optional[str]:
    root = Path(__file__).resolve().parent.parent / "gallery-dl-master"
    if root.exists():
        return str(root)
    return None


def _ensure_gallerydl_module() -> Optional[Any]:
    root = _gallerydl_module_root()
    if root and root not in sys.path:
        sys.path.insert(0, root)
    try:
        import gallery_dl  # type: ignore

        return gallery_dl
    except Exception:  # pragma: no cover - optional dependency
        return None


def _extract_host(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    if not text.startswith(("http://", "https://")):
        text = "https://" + text
    parsed = urlparse(text)
    host = parsed.netloc
    if not host:
        return None
    host = host.lower()
    if "@" in host:
        host = host.split("@", 1)[-1]
    if ":" in host:
        host = host.split(":", 1)[0]
    if host.startswith("www."):
        host = host[4:]
    return host or None


def _candidate_executables(preferred: Optional[str]) -> Tuple[str, ...]:
    candidates: List[str] = []

    def add(path: Optional[str]) -> None:
        if not path:
            return
        if path not in candidates:
            candidates.append(path)

    add(preferred)
    if preferred and not os.path.isabs(preferred):
        resolved = shutil.which(preferred)
        add(resolved)

    env_exec = os.environ.get("GALLERY_DL_EXEC")
    if env_exec:
        add(env_exec)
        if not os.path.isabs(env_exec):
            resolved = shutil.which(env_exec)
            add(resolved)

    for default in ("/usr/local/bin/gallery-dl", "/usr/bin/gallery-dl", "gallery-dl"):
        add(default)
        if not os.path.isabs(default):
            resolved = shutil.which(default)
            add(resolved)

    return tuple(path for path in candidates if path)


def _resolve_domains(executable_path: Optional[str]) -> Tuple[str, ...]:
    for candidate in _candidate_executables(executable_path):
        try:
            domains = _list_gallerydl_domains_cli(candidate)
        except FileNotFoundError:
            log.info("gallery-dl executable not found at %s", candidate)
            continue
        if domains:
            log.info("gallery-dl domains resolved via %s", candidate)
            return domains
    return tuple()


def is_gallerydl_supported(url: str, executable_path: Optional[str] = None) -> bool:
    if not url:
        return False
    for candidate in _candidate_executables(executable_path):
        try:
            # Use --simulate to check if gallery-dl can handle the URL without downloading.
            # This is more reliable than matching against a static list of domains.
            subprocess.run(
                [candidate, "--simulate", url],
                capture_output=True,
                text=True,
                check=True,
            )
            # If the command succeeds (doesn't raise), the URL is supported.
            return True
        except FileNotFoundError:
            continue  # Try the next candidate if this one isn't found
        except subprocess.CalledProcessError:
            # A non-zero exit code means the URL is not supported
            return False
        except Exception as exc:
            log.warning("Failed to check gallery-dl support for %s: %s", url, exc)
            return False
    return False


def list_gallerydl_sites(executable_path: Optional[str] = None) -> List[str]:
    module = _ensure_gallerydl_module()
    hosts: set[str] = set()
    if module:
        try:
            from gallery_dl.extractor import extractors  # type: ignore

            for extr in extractors():
                example = getattr(extr, "example", None)
                host = _extract_host(example)
                if host:
                    hosts.add(host)
        except Exception:  # pragma: no cover - defensive
            log.debug("Falling back to CLI for gallery-dl site list", exc_info=True)

    hosts.update(_resolve_domains(executable_path))
    return sorted(hosts)


def _list_gallerydl_extractors_cli(executable_path: str) -> Tuple[Dict[str, Optional[str]], ...]:
    cached = _extractor_cache.get(executable_path)
    if cached is not None:
        return cached
    try:
        completed = subprocess.run(
            [executable_path, "--list-extractors"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise exc
    except Exception as exc:
        log.warning("Failed to enumerate gallery-dl extractors via %s: %s", executable_path, exc)
        return tuple()

    entries: List[Dict[str, Optional[str]]] = []
    for block in completed.stdout.split("\n\n"):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        name = lines[0]
        category = subcategory = example = None
        for line in lines[1:]:
            if line.startswith("Category:"):
                try:
                    _, rest = line.split("Category:", 1)
                    if "Subcategory:" in rest:
                        cat_part, sub_part = rest.split("Subcategory:", 1)
                        category = cat_part.strip().strip("-").strip()
                        subcategory = sub_part.strip()
                    else:
                        category = rest.strip()
                except ValueError:
                    pass
            elif line.lower().startswith("example"):
                example = line.split(":", 1)[1].strip()
        entries.append(
            {
                "name": name,
                "category": category,
                "subcategory": subcategory,
                "example": example,
                "host": _extract_host(example),
            }
        )
    result = tuple(entries)
    if result:
        _extractor_cache[executable_path] = result
    return result


def _list_gallerydl_domains_cli(executable_path: str) -> Tuple[str, ...]:
    cached = _domain_cache.get(executable_path)
    if cached is not None:
        return cached
    entries = _list_gallerydl_extractors_cli(executable_path)
    hosts = tuple(sorted({entry["host"] for entry in entries if entry.get("host")}))
    log.info("gallery-dl domain cache update: exec=%s count=%d", executable_path, len(hosts))
    if hosts:
        _domain_cache[executable_path] = hosts
    return hosts


def _normalize_options(options: Optional[Iterable[str]]) -> List[str]:
    if not options:
        return []
    sanitized: List[str] = []
    for option in options:
        if not isinstance(option, str):
            continue
        value = option.strip()
        if not value:
            continue
        if len(value) > 200:
            value = value[:200]
        sanitized.append(value)
        if len(sanitized) >= 64:
            break
    if sanitized:
        log.info("gallery-dl options normalized: %s", sanitized)
    return sanitized


class GalleryDlJob:
    def __init__(
        self,
        info: DownloadInfo,
        url: str,
        options: Optional[List[str]] = None,
        *,
        credential_id: Optional[str] = None,
        cookie_name: Optional[str] = None,
        proxy: Optional[str] = None,
        retries: Optional[int] = None,
        sleep_request: Optional[str] = None,
        sleep429: Optional[str] = None,
        write_metadata: bool = False,
        write_info_json: bool = False,
        write_tags: bool = False,
        download_archive: bool = False,
        archive_id: Optional[str] = None,
    ):
        self.info = info
        self.url = url
        self.options = _normalize_options(options)
        self.credential_id = _clean_optional_str(credential_id, 120)
        self.cookie_name = _clean_optional_str(cookie_name, 120)
        self.proxy = _clean_optional_str(proxy, 200)
        self.retries = retries if isinstance(retries, int) and retries >= 0 else None
        self.sleep_request = _clean_optional_str(sleep_request, 50)
        self.sleep_429 = _clean_optional_str(sleep429, 50)
        self.write_metadata = bool(write_metadata)
        self.write_info_json = bool(write_info_json)
        self.write_tags = bool(write_tags)
        self.download_archive = bool(download_archive)
        self.archive_id = _sanitize_archive_name(archive_id) if download_archive else None

        self.process: Optional[subprocess.Popen] = None
        self.temp_dir: Optional[str] = None
        self.archive_path: Optional[str] = None
        self._task: Optional[asyncio.Task] = None
        self._cancel_requested = False
        self._started_at: Optional[float] = None
        self.expected_items: Optional[int] = None
        self.completed_items: int = 0
        self._seen_files: Set[str] = set()
        self._temp_dir_prefix: Optional[str] = None

    def cancel(self):
        self._cancel_requested = True
        if self.process and self.process.poll() is None:
            try:
                self.process.kill()
            except Exception as exc:
                log.warning("Failed to kill gallery-dl process: %s", exc)


class GalleryDlManager:
    def __init__(
        self,
        config,
        notifier,
        state_dir: str,
        executable_path: Optional[str] = None,
        credential_store: Optional["CredentialStore"] = None,
        cookie_store: Optional["CookieStore"] = None,
        max_history_items: int = 200,
    ):
        self.config = config
        self.notifier = notifier
        self.state_dir = os.path.join(state_dir, "gallerydl")
        os.makedirs(self.state_dir, exist_ok=True)
        self._executable_path = executable_path or getattr(config, "GALLERY_DL_EXEC", "gallery-dl")
        self.credential_store = credential_store
        self.cookie_store = cookie_store
        self.archive_dir = os.path.join(self.state_dir, "archives")
        os.makedirs(self.archive_dir, exist_ok=True)

        self.queue: "OrderedDict[str, GalleryDlJob]" = OrderedDict()
        self.pending: "OrderedDict[str, GalleryDlJob]" = OrderedDict()
        self.done: "OrderedDict[str, GalleryDlJob]" = OrderedDict()
        self.max_history_items = max_history_items if max_history_items is not None else 200

        self._semaphore: Optional[asyncio.Semaphore] = None
        if getattr(self.config, "DOWNLOAD_MODE", "limited") == "limited":
            try:
                limit = int(getattr(self.config, "MAX_CONCURRENT_DOWNLOADS", 1))
            except (TypeError, ValueError):
                limit = 1
            self._semaphore = asyncio.Semaphore(max(limit, 1))

        self._completed_state_file = os.path.join(self.state_dir, "completed.json")
        self._load_completed()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def get(self) -> Tuple[List[Tuple[str, DownloadInfo]], List[Tuple[str, DownloadInfo]]]:
        queue_items = [(key, job.info) for key, job in self.queue.items()] + [
            (key, job.info) for key, job in self.pending.items()
        ]
        done_items = [(key, job.info) for key, job in self.done.items()]
        return queue_items, done_items

    async def add_job(
        self,
        *,
        url: str,
        title: Optional[str] = None,
        auto_start: bool = True,
        options: Optional[List[str]] = None,
        credential_id: Optional[str] = None,
        cookie_name: Optional[str] = None,
        proxy: Optional[str] = None,
        retries: Optional[int] = None,
        sleep_request: Optional[str] = None,
        sleep429: Optional[str] = None,
        write_metadata: bool = False,
        write_info_json: bool = False,
        write_tags: bool = False,
        download_archive: bool = False,
        archive_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        job_id = uuid.uuid4().hex
        storage_key = f"gallerydl:{job_id}"
        display_title = title or url

        info = DownloadInfo(
            job_id,
            display_title,
            storage_key,
            "gallery",
            "zip",
            folder="",
            custom_name_prefix="",
            error=None,
            entry=None,
            playlist_item_limit=0,
            cookiefile=None,
            user_id=None,
            original_url=url,
            provider="gallerydl",
        )
        info.status = "pending"
        info.percent = None
        info.speed = None
        info.eta = None

        job = GalleryDlJob(
            info,
            url,
            options,
            credential_id=credential_id,
            cookie_name=cookie_name,
            proxy=proxy,
            retries=retries,
            sleep_request=sleep_request,
            sleep429=sleep429,
            write_metadata=write_metadata,
            write_info_json=write_info_json,
            write_tags=write_tags,
            download_archive=download_archive,
            archive_id=archive_id,
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
            await self._start_download(storage_key, job)
        return {"status": "ok"}

    async def cancel(self, ids: Iterable[str]) -> Dict[str, Any]:
        for storage_key in ids:
            if storage_key in self.pending:
                job = self.pending.pop(storage_key)
                job.info.status = "canceled"
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
            file_path = job.archive_path
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
        status = {"status": "ok", "deleted": deleted, "missing": missing}
        if errors:
            status.update({"status": "error", "errors": errors, "msg": "Some files could not be removed from disk."})
        return status

    async def rename(self, storage_key: str, new_name: str) -> Dict[str, Any]:
        job = self.done.get(storage_key)
        if not job:
            return {"status": "error", "msg": "Download not found."}
        if not new_name or any(sep in new_name for sep in ("/", "\\")):
            return {"status": "error", "msg": "Invalid filename specified."}
        if not job.archive_path or not os.path.exists(job.archive_path):
            return {"status": "error", "msg": "Original file no longer exists."}

        directory = os.path.dirname(job.archive_path)
        sanitized = _sanitize_filename(new_name)
        target_path = os.path.join(directory, sanitized)
        if os.path.exists(target_path):
            return {"status": "error", "msg": "A file with the requested name already exists."}

        try:
            os.rename(job.archive_path, target_path)
        except OSError as exc:
            return {"status": "error", "msg": f"Failed to rename file: {exc}"}

        job.archive_path = target_path
        job.info.filename = os.path.basename(target_path)
        try:
            job.info.size = os.path.getsize(target_path)
        except OSError:
            pass
        await self.notifier.renamed(job.info)
        self._persist_completed()
        return {"status": "ok", "filename": job.info.filename, "title": job.info.title}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    async def _start_download(self, storage_key: str, job: GalleryDlJob) -> None:
        job.info.status = "preparing"
        await self.notifier.updated(job.info)

        async def runner():
            if self._semaphore:
                async with self._semaphore:
                    await self._run_job(storage_key, job)
            else:
                await self._run_job(storage_key, job)

        job._task = asyncio.create_task(runner())

    async def _run_job(self, storage_key: str, job: GalleryDlJob) -> None:
        job.temp_dir = tempfile.mkdtemp(prefix="gallerydl-", dir=getattr(self.config, "TEMP_DIR", None))
        base_directory = job.temp_dir
        job._temp_dir_prefix = os.path.normpath(job.temp_dir) + os.sep
        job._seen_files.clear()
        job.completed_items = 0
        try:
            cmd = self._build_command(job, base_directory)
        except Exception as exc:
            job.info.status = "error"
            job.info.msg = str(exc)
            await self._finalize_failure(storage_key, job)
            self._cleanup_temp(job)
            return

        log.info("Starting gallery-dl job %s: %s", storage_key, cmd)
        try:
            job.info.status = "preparing"
            job.info.msg = "Analyzing gallery"
            await self.notifier.updated(job.info)

            await self._estimate_expected_items(job, base_directory, cmd)

            if job._cancel_requested:
                job.info.status = "canceled"
                job.info.msg = "Download canceled"
                await self.notifier.updated(job.info)
                self.queue.pop(storage_key, None)
                self._cleanup_temp(job)
                return

            job.info.status = "downloading"
            job.info.msg = "Starting gallery-dl"
            job._started_at = time.time()
            await self.notifier.updated(job.info)

            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=base_directory,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            job.process = process

            stdout_chunks: List[str] = []
            assert process.stdout is not None
            async for raw_line in process.stdout:
                line = raw_line.decode(errors="ignore").strip()
                if not line:
                    continue
                stdout_chunks.append(line)
                progress_msg = self._update_progress_from_line(job, line)
                job.info.msg = progress_msg or line
                await self.notifier.updated(job.info)
            returncode = await process.wait()

            if job._cancel_requested:
                job.info.status = "canceled"
                job.info.msg = "Download canceled"
                await self.notifier.updated(job.info)
                self.queue.pop(storage_key, None)
                self._cleanup_temp(job)
                return

            if returncode != 0:
                log.error(
                    "gallery-dl job %s failed with exit code %s\nCommand: %s\nOutput:\n%s",
                    storage_key,
                    returncode,
                    cmd,
                    "\n".join(stdout_chunks),
                )
                job.info.status = "error"
                job.info.msg = f"gallery-dl exited with code {returncode}"
                job.info.log = "\n".join(stdout_chunks)
                await self._finalize_failure(storage_key, job)
                return

            archive_path = await asyncio.get_running_loop().run_in_executor(None, self._archive_results, job)
            if not archive_path:
                job.info.status = "error"
                job.info.msg = "Failed to package gallery-dl results"
                await self._finalize_failure(storage_key, job)
                return

            job.archive_path = archive_path
            job.info.filename = os.path.basename(archive_path)
            try:
                job.info.size = os.path.getsize(archive_path)
            except OSError:
                job.info.size = None
            job.info.status = "finished"
            job.info.msg = "Download completed"
            job.info.percent = 100.0
            job.info.timestamp = time.time_ns()

            self.queue.pop(storage_key, None)
            self.done[storage_key] = job
            self._persist_completed()
            await self.notifier.completed(job.info)
        except Exception as exc:
            log.error("gallery-dl job failed: %s", exc)
            job.info.status = "error"
            job.info.msg = str(exc)
            await self._finalize_failure(storage_key, job)
        finally:
            self._cleanup_temp(job)

    def _build_command(self, job: GalleryDlJob, base_directory: str) -> List[str]:
        executable = self._resolve_executable()
        cmd = [executable]
        if executable.endswith("python") or executable.endswith("python.exe"):
            cmd.extend(["-m", "gallery_dl"])
        if "-m" not in cmd and os.path.basename(executable).startswith("python"):
            cmd.extend(["-m", "gallery_dl"])

        cmd.extend([
            "--ignore-config",
            "--destination",
            base_directory,
        ])
        cmd.extend(self._credential_arguments(job))
        cmd.extend(self._cookie_arguments(job))
        cmd.extend(self._network_arguments(job))
        cmd.extend(self._metadata_arguments(job))
        cmd.extend(job.options)
        cmd.append(job.url)
        return cmd

    async def _estimate_expected_items(self, job: GalleryDlJob, base_directory: str, base_cmd: List[str]) -> None:
        if job.expected_items is not None:
            return

        if job.options:
            lowered = [opt.lower() for opt in job.options if isinstance(opt, str)]
            if any(opt.startswith("--print") or opt in {"--dump-json", "-g", "--get-urls", "--simulate", "-s"} for opt in lowered):
                return

        estimate_cmd = list(base_cmd)
        if not estimate_cmd:
            return

        url = estimate_cmd.pop()
        estimate_cmd.extend(["--print", "file:{num}", url])

        log.debug("Estimating gallery item count for %s using %s", job.url, estimate_cmd)

        try:
            process = await asyncio.create_subprocess_exec(
                *estimate_cmd,
                cwd=base_directory,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except FileNotFoundError:
            log.warning("Unable to estimate gallery size; gallery-dl executable missing")
            return
        except Exception as exc:
            log.warning("Unable to estimate gallery size for %s: %s", job.url, exc)
            return

        assert process.stdout is not None
        count = 0
        highest = 0

        async def _consume() -> None:
            nonlocal count, highest
            async for raw_line in process.stdout:  # type: ignore[attr-defined]
                line = raw_line.decode(errors="ignore").strip()
                if not line:
                    continue
                try:
                    value = int(line.split()[0])
                except ValueError:
                    continue
                count += 1
                if value > highest:
                    highest = value

        try:
            await asyncio.wait_for(_consume(), timeout=60.0)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            log.warning("Timed out estimating gallery size for %s", job.url)
            return
        except asyncio.CancelledError:
            process.kill()
            raise

        returncode = await process.wait()
        if returncode != 0:
            log.debug("gallery-dl size estimation exited with %s for %s", returncode, job.url)
            return

        total = highest or count
        if total <= 0:
            return

        job.expected_items = total
        job.completed_items = 0
        job.info.percent = 0.0
        job.info.msg = f"Found {total} items"
        await self.notifier.updated(job.info)

    def _credential_arguments(self, job: GalleryDlJob) -> List[str]:
        if not job.credential_id:
            return []
        if not self.credential_store:
            raise RuntimeError("Credential store is not configured")

        record = self.credential_store.get_credential(job.credential_id)
        if not record:
            raise RuntimeError("Credential profile not found")

        values = record.get("values", {}) or {}
        args: List[str] = []
        username = _clean_optional_str(values.get("username"))
        if username:
            args.extend(["--username", username])
        password = values.get("password")
        if password:
            args.extend(["--password", password])
        twofactor = _clean_optional_str(values.get("twofactor"))
        if twofactor:
            args.extend(["--twofactor", twofactor])

        extra_args = values.get("extra_args") or []
        for entry in extra_args:
            if not isinstance(entry, str):
                continue
            tokens = self._tokenize_argument(entry)
            args.extend(tokens)
        return args

    def _cookie_arguments(self, job: GalleryDlJob) -> List[str]:
        if not job.cookie_name:
            return []
        if not self.cookie_store:
            raise RuntimeError("Cookie store is not configured")
        path = self.cookie_store.resolve_path(job.cookie_name)
        if not os.path.exists(path):
            raise RuntimeError("Cookie file not found")
        return ["--cookies", path]

    def _network_arguments(self, job: GalleryDlJob) -> List[str]:
        args: List[str] = []
        if job.proxy:
            args.extend(["--proxy", job.proxy])
        if job.retries is not None:
            args.extend(["--retries", str(job.retries)])
        if job.sleep_request:
            args.extend(["--sleep-request", job.sleep_request])
        if job.sleep_429:
            args.extend(["--sleep-429", job.sleep_429])
        return args

    def _metadata_arguments(self, job: GalleryDlJob) -> List[str]:
        args: List[str] = []
        if job.write_metadata:
            args.append("--write-metadata")
        if job.write_info_json:
            args.append("--write-info-json")
        if job.write_tags:
            args.append("--write-tags")
        if job.download_archive:
            archive_name = job.archive_id or _sanitize_archive_name(_extract_host(job.url), "default")
            archive_path = os.path.join(self.archive_dir, f"{archive_name}.txt")
            args.extend(["--download-archive", archive_path])
        return args

    def _tokenize_argument(self, value: str) -> List[str]:
        try:
            tokens = shlex.split(value)
            return tokens or [value]
        except ValueError:
            return [value]

    def _update_progress_from_line(self, job: GalleryDlJob, line: str) -> Optional[str]:
        progress_msg: Optional[str] = None

        ratio_match = re.search(r"(\d+)\s*/\s*(\d+)", line)
        if ratio_match:
            current = int(ratio_match.group(1))
            total = int(ratio_match.group(2))
            if total > 0:
                percent = min(100.0, (current / total) * 100.0)
                job.info.percent = percent
                progress_msg = f"{current}/{total} ({percent:.1f}%)"
        else:
            percent_match = re.search(r"(\d+(?:\.\d+)?)%", line)
            if percent_match:
                percent = float(percent_match.group(1))
                if percent >= 0:
                    job.info.percent = min(percent, 100.0)
                    progress_msg = f"{job.info.percent:.1f}%"

        path_progress = self._handle_path_progress(job, line)
        if path_progress:
            return path_progress

        return progress_msg

    def _handle_path_progress(self, job: GalleryDlJob, line: str) -> Optional[str]:
        if not line:
            return None

        normalized = line[2:] if line.startswith("# ") else line
        temp_dir = job.temp_dir
        if not temp_dir:
            return None

        if normalized.startswith("./") or normalized.startswith(".\\"):
            normalized = normalized[2:]
        normalized_path = os.path.normpath(os.path.join(temp_dir, normalized))

        prefix = job._temp_dir_prefix
        if prefix and not normalized_path.startswith(prefix):
            # gallery-dl may emit absolute paths already
            abs_path = os.path.normpath(normalized)
            if abs_path.startswith(prefix):
                normalized_path = abs_path
            else:
                return None

        basename = os.path.basename(normalized_path)
        if not basename or basename in job._seen_files:
            return None

        lower_basename = basename.lower()
        if not any(lower_basename.endswith(ext) for ext in _FILE_EXTENSIONS):
            return None

        job._seen_files.add(basename)
        job.completed_items += 1

        if job.expected_items:
            if job.completed_items > job.expected_items:
                job.expected_items = job.completed_items
            job.info.percent = min(100.0, (job.completed_items / job.expected_items) * 100.0)
            return f"{basename} ({job.completed_items}/{job.expected_items})"

        job.info.percent = None
        return f"{basename} ({job.completed_items} files)"

    def _resolve_executable(self) -> str:
        exec_path = self._executable_path
        if exec_path.lower() == "python":
            return exec_path
        if os.path.isabs(exec_path) and os.path.exists(exec_path):
            return exec_path
        return exec_path

    async def _finalize_failure(self, storage_key: str, job: GalleryDlJob) -> None:
        await self.notifier.updated(job.info)
        self.queue.pop(storage_key, None)
        job.info.timestamp = time.time_ns()
        self.done[storage_key] = job
        self._persist_completed()
        await self.notifier.completed(job.info)

    def _archive_results(self, job: GalleryDlJob) -> Optional[str]:
        if not job.temp_dir:
            return None
        download_dir = getattr(self.config, "DOWNLOAD_DIR", ".")
        os.makedirs(download_dir, exist_ok=True)
        base_name = _sanitize_filename(f"{job.info.title or 'gallery'}-{job.info.id}") + ".zip"
        archive_path = os.path.join(download_dir, base_name)

        counter = 1
        while os.path.exists(archive_path):
            base_name = _sanitize_filename(f"{job.info.title or 'gallery'}-{job.info.id}-{counter}") + ".zip"
            archive_path = os.path.join(download_dir, base_name)
            counter += 1

        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zip_fp:
            for root, _, files in os.walk(job.temp_dir):
                for filename in files:
                    abs_path = os.path.join(root, filename)
                    rel_path = os.path.relpath(abs_path, job.temp_dir)
                    zip_fp.write(abs_path, rel_path)

        return archive_path

    def _cleanup_temp(self, job: GalleryDlJob) -> None:
        if job.temp_dir and os.path.isdir(job.temp_dir):
            try:
                shutil.rmtree(job.temp_dir)
            except Exception as exc:
                log.debug("Failed to cleanup temp dir %s: %s", job.temp_dir, exc)
        job.temp_dir = None
        job._temp_dir_prefix = None

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _load_completed(self) -> None:
        if not os.path.exists(self._completed_state_file):
            return
        try:
            with open(self._completed_state_file, "r", encoding="utf-8") as fp:
                data = json.load(fp)
        except (OSError, json.JSONDecodeError) as exc:
            log.error("Failed to load gallery-dl history: %s", exc)
            return

        for record in data:
            job_id = record.get("id")
            storage_key = record.get("storage_key")
            if not job_id or not storage_key:
                continue
            info = DownloadInfo(
                job_id,
                record.get("title") or job_id,
                storage_key,
                record.get("quality", "gallery"),
                record.get("format", "zip"),
                folder="",
                custom_name_prefix="",
                error=None,
                entry=None,
                playlist_item_limit=0,
                cookiefile=None,
                user_id=None,
                original_url=record.get("original_url"),
                provider="gallerydl",
            )
            info.status = record.get("status", "finished")
            info.filename = record.get("filename")
            info.size = record.get("size")
            info.timestamp = record.get("timestamp", time.time_ns())
            info.msg = record.get("msg")
            info.percent = 100.0 if info.status == "finished" else None

            job = GalleryDlJob(
                info,
                record.get("url") or record.get("original_url") or "",
                options=record.get("options"),
                credential_id=record.get("credential_id"),
                cookie_name=record.get("cookie_name"),
                proxy=record.get("proxy"),
                retries=record.get("retries"),
                sleep_request=record.get("sleep_request"),
                sleep429=record.get("sleep_429"),
                write_metadata=record.get("write_metadata", False),
                write_info_json=record.get("write_info_json", False),
                write_tags=record.get("write_tags", False),
                download_archive=record.get("download_archive", False),
                archive_id=record.get("archive_id"),
            )
            job.archive_path = record.get("archive_path")
            self.done[storage_key] = job
        if self._enforce_history_limit():
            self._persist_completed()

    def _persist_completed(self) -> None:
        self._enforce_history_limit()
        data = []
        for storage_key, job in self.done.items():
            info = job.info
            data.append(
                {
                    "id": info.id,
                    "storage_key": storage_key,
                    "title": info.title,
                    "filename": info.filename,
                    "size": info.size,
                    "status": info.status,
                    "msg": info.msg,
                    "timestamp": info.timestamp,
                    "url": job.url,
                    "original_url": info.original_url,
                    "archive_path": job.archive_path,
                    "quality": info.quality,
                    "format": info.format,
                    "options": job.options,
                    "credential_id": job.credential_id,
                    "cookie_name": job.cookie_name,
                    "proxy": job.proxy,
                    "retries": job.retries,
                    "sleep_request": job.sleep_request,
                    "sleep_429": job.sleep_429,
                    "write_metadata": job.write_metadata,
                    "write_info_json": job.write_info_json,
                    "write_tags": job.write_tags,
                    "download_archive": job.download_archive,
                    "archive_id": job.archive_id,
                }
            )
        try:
            with open(self._completed_state_file, "w", encoding="utf-8") as fp:
                json.dump(data, fp)
        except OSError as exc:
            log.error("Failed to persist gallery-dl history: %s", exc)

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

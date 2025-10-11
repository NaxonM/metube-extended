import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

_extractor_cache: Dict[str, Tuple[Dict[str, Optional[str]], ...]] = {}
_domain_cache: Dict[str, Tuple[str, ...]] = {}

from ytdl import DownloadInfo

log = logging.getLogger("gallerydl")


def _sanitize_filename(value: str) -> str:
    sanitized = value.replace("\0", "").strip()
    invalid = '\\/:*?"<>|'
    for ch in invalid:
        sanitized = sanitized.replace(ch, "_")
    sanitized = sanitized.replace("..", "_")
    return sanitized or f"gallerydl-{uuid.uuid4().hex}"


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
    module = _ensure_gallerydl_module()
    if module:
        try:
            from gallery_dl.extractor import find  # type: ignore

            return find(url) is not None
        except Exception:  # pragma: no cover - defensive
            pass

    host = _extract_host(url)
    if not host:
        return False

    domains = _resolve_domains(executable_path)
    if not domains:
        log.info("gallery-dl support check: no domains resolved for executable %s", executable_path)
        return False
    result = any(host == domain or host.endswith(f".{domain}") for domain in domains)
    log.info("gallery-dl support check: host=%s match=%s", host, result)
    return result


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
    def __init__(self, info: DownloadInfo, url: str, options: Optional[List[str]] = None):
        self.info = info
        self.url = url
        self.options = _normalize_options(options)
        self.process: Optional[subprocess.Popen] = None
        self.temp_dir: Optional[str] = None
        self.archive_path: Optional[str] = None
        self._task: Optional[asyncio.Task] = None
        self._cancel_requested = False
        self._started_at: Optional[float] = None

    def cancel(self):
        self._cancel_requested = True
        if self.process and self.process.poll() is None:
            try:
                self.process.kill()
            except Exception as exc:
                log.warning("Failed to kill gallery-dl process: %s", exc)


class GalleryDlManager:
    def __init__(self, config, notifier, state_dir: str, executable_path: Optional[str] = None):
        self.config = config
        self.notifier = notifier
        self.state_dir = os.path.join(state_dir, "gallerydl")
        os.makedirs(self.state_dir, exist_ok=True)
        self._executable_path = executable_path or getattr(config, "GALLERY_DL_EXEC", "gallery-dl")

        self.queue: "OrderedDict[str, GalleryDlJob]" = OrderedDict()
        self.pending: "OrderedDict[str, GalleryDlJob]" = OrderedDict()
        self.done: "OrderedDict[str, GalleryDlJob]" = OrderedDict()

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

        job = GalleryDlJob(info, url, options)
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
        cmd = self._build_command(job, base_directory)

        log.info("Starting gallery-dl job %s: %s", storage_key, cmd)
        try:
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

            assert process.stdout is not None
            async for raw_line in process.stdout:
                line = raw_line.decode(errors="ignore").strip()
                if not line:
                    continue
                job.info.msg = line
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
                job.info.status = "error"
                job.info.msg = f"gallery-dl exited with code {returncode}"
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
            "--base-directory",
            base_directory,
        ])
        cmd.extend(job.options)
        cmd.append(job.url)
        return cmd

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

            job = GalleryDlJob(info, record.get("url") or record.get("original_url") or "", options=record.get("options"))
            job.archive_path = record.get("archive_path")
            self.done[storage_key] = job

    def _persist_completed(self) -> None:
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
                }
            )
        try:
            with open(self._completed_state_file, "w", encoding="utf-8") as fp:
                json.dump(data, fp)
        except OSError as exc:
            log.error("Failed to persist gallery-dl history: %s", exc)

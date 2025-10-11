import json
import os
import threading
import time
import uuid
from contextlib import suppress
from typing import Any, Dict, List, Optional


def _sanitize_name(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("Cookie profile name cannot be empty")
    if len(cleaned) > 120:
        raise ValueError("Cookie profile name is too long")
    if not all(ch.isalnum() or ch in ("-", "_", ".", " ") for ch in cleaned):
        raise ValueError("Cookie profile name contains invalid characters")
    return cleaned


def _sanitize_tag(value: str) -> str:
    cleaned = value.strip().lower()
    if not cleaned:
        raise ValueError("Tag cannot be empty")
    if len(cleaned) > 80:
        raise ValueError("Tag is too long")
    if not all(ch.isalnum() or ch in ("-", "_", ".") for ch in cleaned):
        raise ValueError("Tag contains invalid characters")
    return cleaned


class CookieProfileStore:
    def __init__(self, directory: str):
        self.directory = directory
        os.makedirs(self.directory, exist_ok=True)
        self.index_path = os.path.join(self.directory, "profiles.json")
        self._lock = threading.Lock()
        if not os.path.exists(self.index_path):
            self._save_index({"profiles": []})

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------
    def _load_index(self) -> Dict[str, Any]:
        with self._lock:
            with open(self.index_path, "r", encoding="utf-8") as fh:
                return json.load(fh)

    def _save_index(self, data: Dict[str, Any]) -> None:
        with self._lock:
            tmp_path = f"{self.index_path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            os.replace(tmp_path, self.index_path)

    def _profile_path(self, profile_id: str) -> str:
        return os.path.join(self.directory, f"{profile_id}.cookies")

    # ------------------------------------------------------------------
    # CRUD operations
    # ------------------------------------------------------------------
    def list_profiles(self) -> List[Dict[str, Any]]:
        data = self._load_index()
        return data.get("profiles", [])

    def get_profile(self, profile_id: str) -> Optional[Dict[str, Any]]:
        data = self._load_index()
        for entry in data.get("profiles", []):
            if entry.get("id") == profile_id:
                return entry
        return None

    def read_cookies(self, profile_id: str) -> str:
        path = self._profile_path(profile_id)
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()

    def save_profile(
        self,
        *,
        name: str,
        cookies: Optional[str] = None,
        tags: Optional[List[str]] = None,
        hosts: Optional[List[str]] = None,
        default: bool = False,
        profile_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        record_name = _sanitize_name(name)
        normalized_tags = []
        if tags:
            seen = set()
            for tag in tags:
                try:
                    value = _sanitize_tag(tag)
                except ValueError:
                    continue
                if value in seen:
                    continue
                seen.add(value)
                normalized_tags.append(value)
        normalized_hosts = []
        if hosts:
            seen_hosts = set()
            for host in hosts:
                value = host.strip().lower()
                if not value:
                    continue
                if len(value) > 200:
                    value = value[:200]
                if value in seen_hosts:
                    continue
                seen_hosts.add(value)
                normalized_hosts.append(value)

        data = self._load_index()
        profiles = data.setdefault("profiles", [])

        if profile_id:
            entry = None
            for item in profiles:
                if item.get("id") == profile_id:
                    entry = item
                    break
            if not entry:
                raise KeyError("Cookie profile not found")
            existing_cookies = None
            if cookies is None:
                existing_cookies = self.read_cookies(profile_id)
            cookies_to_store = cookies if cookies is not None else existing_cookies
        else:
            profile_id = uuid.uuid4().hex
            entry = {
                "id": profile_id,
                "created_at": time.time(),
            }
            profiles.append(entry)
            cookies_to_store = cookies

        if cookies_to_store is None or not cookies_to_store.strip():
            raise ValueError("Cookie data cannot be empty")

        entry.update(
            {
                "name": record_name,
                "tags": normalized_tags,
                "hosts": normalized_hosts,
                "default": bool(default),
                "updated_at": time.time(),
                "last_used_at": entry.get("last_used_at"),
            }
        )

        path = self._profile_path(profile_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(cookies_to_store.rstrip("\n") + "\n")
        try:
            os.chmod(path, 0o600)
        except PermissionError:
            pass

        if entry["default"]:
            for item in profiles:
                if item.get("id") != profile_id:
                    item["default"] = False

        entry.setdefault("last_used_at", None)
        self._save_index(data)
        return entry.copy()

    def delete_profile(self, profile_id: str) -> None:
        data = self._load_index()
        profiles = data.get("profiles", [])
        new_profiles = [entry for entry in profiles if entry.get("id") != profile_id]
        if len(new_profiles) == len(profiles):
            raise KeyError("Cookie profile not found")
        data["profiles"] = new_profiles
        self._save_index(data)
        path = self._profile_path(profile_id)
        with suppress(FileNotFoundError):
            os.remove(path)

    def resolve_profile_path(self, profile_id: str) -> Optional[str]:
        path = self._profile_path(profile_id)
        return path if os.path.exists(path) else None

    def touch_profile(self, profile_id: str) -> None:
        data = self._load_index()
        updated = False
        for entry in data.get("profiles", []):
            if entry.get("id") == profile_id:
                entry["last_used_at"] = time.time()
                updated = True
                break
        if updated:
            self._save_index(data)

    # ------------------------------------------------------------------
    # Matching utilities
    # ------------------------------------------------------------------
    def auto_match_profile(self, url: str, tags: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
        profiles = self.list_profiles()
        if not profiles:
            return None

        parsed_host = _extract_host(url)
        normalized_tags = {t.strip().lower() for t in (tags or []) if t}

        best_match = None
        best_score = -1
        for entry in profiles:
            score = 0
            hosts = entry.get("hosts") or []
            tags_list = entry.get("tags") or []
            if parsed_host and hosts:
                for host in hosts:
                    if parsed_host == host:
                        score += 20
                    elif parsed_host.endswith(host):
                        score += 15
            if normalized_tags and tags_list:
                overlap = len(normalized_tags.intersection(set(tags_list)))
                score += overlap * 10
            if entry.get("default"):
                score += 1
            if score > best_score:
                best_score = score
                best_match = entry

        if best_match is not None:
            return best_match

        for entry in profiles:
            if entry.get("default"):
                return entry
        return None


def _extract_host(url: str) -> Optional[str]:
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        if not parsed.netloc:
            return None
        host = parsed.netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return None

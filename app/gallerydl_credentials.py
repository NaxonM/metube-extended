import base64
import hashlib
import json
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from cryptography.fernet import Fernet, InvalidToken


def _build_fernet(secret_key_hex: str) -> Fernet:
    raw = bytes.fromhex(secret_key_hex)
    digest = hashlib.sha256(raw).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _sanitize_name(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("Name cannot be empty")
    if len(cleaned) > 120:
        raise ValueError("Name is too long")
    return cleaned


def _sanitize_cookie_name(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("Cookie name cannot be empty")
    if len(cleaned) > 120:
        raise ValueError("Cookie name is too long")
    if not all(ch.isalnum() or ch in ("-", "_", ".") for ch in cleaned):
        raise ValueError("Cookie name contains invalid characters")
    return cleaned


class CredentialStore:
    def __init__(self, directory: str, secret_key_hex: str):
        self.directory = directory
        os.makedirs(self.directory, exist_ok=True)
        self.path = os.path.join(self.directory, "credentials.json")
        self._lock = threading.Lock()
        self._fernet = _build_fernet(secret_key_hex)
        if not os.path.exists(self.path):
            self._save({"credentials": []})

    def _load(self) -> Dict[str, Any]:
        with self._lock:
            with open(self.path, "r", encoding="utf-8") as fh:
                return json.load(fh)

    def _save(self, data: Dict[str, Any]) -> None:
        with self._lock:
            tmp_path = f"{self.path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            os.replace(tmp_path, self.path)

    def _encrypt(self, payload: Dict[str, Any]) -> str:
        serialized = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return self._fernet.encrypt(serialized).decode("utf-8")

    def _decrypt(self, token: str) -> Dict[str, Any]:
        try:
            decrypted = self._fernet.decrypt(token.encode("utf-8"))
            return json.loads(decrypted.decode("utf-8"))
        except (InvalidToken, json.JSONDecodeError) as exc:
            raise ValueError("Unable to decrypt credentials") from exc

    def list_credentials(self) -> List[Dict[str, Any]]:
        data = self._load()
        results: List[Dict[str, Any]] = []
        for entry in data.get("credentials", []):
            try:
                payload = self._decrypt(entry["data"])
            except ValueError:
                payload = {}
            results.append(
                {
                    "id": entry.get("id"),
                    "name": entry.get("name"),
                    "extractor": entry.get("extractor"),
                    "created_at": entry.get("created_at"),
                    "updated_at": entry.get("updated_at"),
                    "username": payload.get("username"),
                    "has_password": bool(payload.get("password")),
                }
            )
        return results

    def get_credential(self, credential_id: str) -> Optional[Dict[str, Any]]:
        data = self._load()
        for entry in data.get("credentials", []):
            if entry.get("id") == credential_id:
                payload = self._decrypt(entry["data"])
                result = entry.copy()
                result.pop("data", None)
                result["values"] = payload
                return result
        return None

    def create_credential(
        self,
        *,
        name: str,
        extractor: Optional[str],
        username: Optional[str],
        password: Optional[str],
        twofactor: Optional[str],
        extra_args: Optional[List[str]],
    ) -> Dict[str, Any]:
        record_name = _sanitize_name(name)
        extractor_value = extractor.strip() if extractor else None

        payload = {
            "username": (username or "").strip() or None,
            "password": password or None,
            "twofactor": (twofactor or "").strip() or None,
            "extra_args": self._normalize_args(extra_args),
        }

        timestamp = time.time()
        entry = {
            "id": uuid.uuid4().hex,
            "name": record_name,
            "extractor": extractor_value,
            "created_at": timestamp,
            "updated_at": timestamp,
            "data": self._encrypt(payload),
        }
        data = self._load()
        data.setdefault("credentials", []).append(entry)
        self._save(data)
        result = entry.copy()
        result.pop("data", None)
        return result

    def update_credential(
        self,
        credential_id: str,
        *,
        name: Optional[str] = None,
        extractor: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        twofactor: Optional[str] = None,
        extra_args: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        data = self._load()
        for idx, entry in enumerate(data.get("credentials", [])):
            if entry.get("id") != credential_id:
                continue
            payload = self._decrypt(entry["data"])

            if name is not None:
                entry["name"] = _sanitize_name(name)
            if extractor is not None:
                entry["extractor"] = extractor.strip() or None
            if username is not None:
                payload["username"] = username.strip() or None
            if password is not None:
                payload["password"] = password
            if twofactor is not None:
                payload["twofactor"] = twofactor.strip() or None
            if extra_args is not None:
                payload["extra_args"] = self._normalize_args(extra_args)

            entry["updated_at"] = time.time()
            entry["data"] = self._encrypt(payload)
            data["credentials"][idx] = entry
            self._save(data)
            result = entry.copy()
            result.pop("data", None)
            return result
        raise KeyError("Credential not found")

    def delete_credential(self, credential_id: str) -> None:
        data = self._load()
        before = len(data.get("credentials", []))
        data["credentials"] = [entry for entry in data.get("credentials", []) if entry.get("id") != credential_id]
        if len(data.get("credentials", [])) == before:
            raise KeyError("Credential not found")
        self._save(data)

    def _normalize_args(self, args: Optional[List[str]]) -> List[str]:
        if not args:
            return []
        normalized: List[str] = []
        for item in args:
            if not isinstance(item, str):
                continue
            value = item.strip()
            if not value:
                continue
            if len(value) > 200:
                value = value[:200]
            normalized.append(value)
            if len(normalized) >= 32:
                break
        return normalized


class CookieStore:
    def __init__(self, directory: str):
        self.directory = os.path.join(directory, "cookies")
        os.makedirs(self.directory, exist_ok=True)

    def list_cookies(self) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for filename in os.listdir(self.directory):
            path = os.path.join(self.directory, filename)
            if not os.path.isfile(path):
                continue
            stats = os.stat(path)
            results.append(
                {
                    "name": filename,
                    "size": stats.st_size,
                    "updated_at": stats.st_mtime,
                }
            )
        results.sort(key=lambda item: item["name"].lower())
        return results

    def save_cookie(self, name: str, content: str) -> Dict[str, Any]:
        safe_name = _sanitize_cookie_name(name)
        path = os.path.join(self.directory, safe_name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        stats = os.stat(path)
        return {"name": safe_name, "size": stats.st_size, "updated_at": stats.st_mtime}

    def delete_cookie(self, name: str) -> None:
        safe_name = _sanitize_cookie_name(name)
        path = os.path.join(self.directory, safe_name)
        if not os.path.exists(path):
            raise FileNotFoundError("Cookie not found")
        os.remove(path)

    def read_cookie(self, name: str) -> str:
        safe_name = _sanitize_cookie_name(name)
        path = os.path.join(self.directory, safe_name)
        if not os.path.exists(path):
            raise FileNotFoundError("Cookie not found")
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()

    def resolve_path(self, name: str) -> str:
        safe_name = _sanitize_cookie_name(name)
        return os.path.join(self.directory, safe_name)

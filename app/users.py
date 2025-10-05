import json
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

import bcrypt


class UserStore:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        if not os.path.exists(self.path):
            self._save({"users": []})

    # --- Internal helpers ---
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

    def _hash_password(self, password: str) -> str:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    # --- Public API ---
    def list_users(self, include_sensitive: bool = False) -> List[Dict[str, Any]]:
        data = self._load()
        users = []
        for user in data.get("users", []):
            user_copy = user.copy()
            if not include_sensitive:
                user_copy.pop("password_hash", None)
            users.append(user_copy)
        return users

    def _find_user_index(self, data: Dict[str, Any], username: Optional[str] = None, user_id: Optional[str] = None) -> int:
        for idx, user in enumerate(data.get("users", [])):
            if username and user.get("username") == username:
                return idx
            if user_id and user.get("id") == user_id:
                return idx
        return -1

    def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        data = self._load()
        idx = self._find_user_index(data, username=username)
        if idx == -1:
            return None
        return data["users"][idx]

    def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        data = self._load()
        idx = self._find_user_index(data, user_id=user_id)
        if idx == -1:
            return None
        return data["users"][idx]

    def create_user(self, username: str, password: str, role: str = "user", disabled: bool = False) -> Dict[str, Any]:
        username = username.strip()
        if not username:
            raise ValueError("Username cannot be empty")
        if role not in ("admin", "user"):
            raise ValueError("Invalid role")

        data = self._load()
        if any(u.get("username") == username for u in data.get("users", [])):
            raise ValueError("Username already exists")

        user = {
            "id": uuid.uuid4().hex,
            "username": username,
            "password_hash": self._hash_password(password),
            "role": role,
            "disabled": disabled,
            "created_at": time.time(),
            "updated_at": time.time(),
            "last_login_at": None,
        }
        data.setdefault("users", []).append(user)
        self._save(data)
        user_copy = user.copy()
        user_copy.pop("password_hash", None)
        return user_copy

    def set_password(self, user_id: str, password: str) -> None:
        data = self._load()
        idx = self._find_user_index(data, user_id=user_id)
        if idx == -1:
            raise KeyError("User not found")
        data["users"][idx]["password_hash"] = self._hash_password(password)
        data["users"][idx]["updated_at"] = time.time()
        self._save(data)

    def set_role(self, user_id: str, role: str) -> None:
        if role not in ("admin", "user"):
            raise ValueError("Invalid role")
        data = self._load()
        idx = self._find_user_index(data, user_id=user_id)
        if idx == -1:
            raise KeyError("User not found")
        data["users"][idx]["role"] = role
        data["users"][idx]["updated_at"] = time.time()
        self._save(data)

    def set_disabled(self, user_id: str, disabled: bool) -> None:
        data = self._load()
        idx = self._find_user_index(data, user_id=user_id)
        if idx == -1:
            raise KeyError("User not found")
        data["users"][idx]["disabled"] = disabled
        data["users"][idx]["updated_at"] = time.time()
        self._save(data)

    def delete_user(self, user_id: str) -> None:
        data = self._load()
        idx = self._find_user_index(data, user_id=user_id)
        if idx == -1:
            raise KeyError("User not found")
        data["users"].pop(idx)
        self._save(data)

    def validate_credentials(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        user = self.get_user(username)
        if not user:
            return None
        if user.get("disabled"):
            return None
        if not bcrypt.checkpw(password.encode(), user.get("password_hash", "").encode()):
            return None
        return user

    def record_login(self, user_id: str) -> None:
        data = self._load()
        idx = self._find_user_index(data, user_id=user_id)
        if idx == -1:
            return
        data["users"][idx]["last_login_at"] = time.time()
        data["users"][idx]["updated_at"] = time.time()
        self._save(data)

    def ensure_admin_user(self, username: str, password: str) -> Dict[str, Any]:
        user = self.get_user(username)
        if user:
            return user
        return self.create_user(username, password, role="admin")

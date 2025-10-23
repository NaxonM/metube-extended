import base64
import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from cryptography.fernet import Fernet, InvalidToken

from seedrcc import Token


def _build_token_fernet(secret_key_hex: str) -> Fernet:
    try:
        raw = bytes.fromhex(secret_key_hex)
    except ValueError as exc:
        raise ValueError("SECRET_KEY must be a 64-character hexadecimal string") from exc

    if len(raw) != 32:
        raise ValueError("SECRET_KEY must be a 64-character hexadecimal string")

    digest = hashlib.sha256(raw + b"seedr-token-store").digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


@dataclass
class SeedrTokenRecord:
    token: Token
    account: Optional[Dict[str, Any]]
    created_at: float
    updated_at: float


class SeedrCredentialStore:
    """Per-user encrypted Seedr token and device-challenge storage."""

    def __init__(self, directory: str, secret_key_hex: str) -> None:
        if not secret_key_hex:
            raise ValueError("SECRET_KEY must be configured to enable Seedr integration")

        self.directory = directory
        os.makedirs(self.directory, exist_ok=True)
        self.token_path = os.path.join(self.directory, "token.json")
        self.challenge_path = os.path.join(self.directory, "device_challenge.json")
        self._fernet = _build_token_fernet(secret_key_hex)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Token handling
    # ------------------------------------------------------------------
    def load_token(self) -> Optional[SeedrTokenRecord]:
        with self._lock:
            if not os.path.exists(self.token_path):
                return None
            try:
                with open(self.token_path, "r", encoding="utf-8") as fh:
                    payload = json.load(fh)
            except (OSError, json.JSONDecodeError):
                return None

            encrypted = payload.get("token")
            if not isinstance(encrypted, str):
                return None

            try:
                decrypted = self._fernet.decrypt(encrypted.encode("utf-8"))
                token_data = json.loads(decrypted.decode("utf-8"))
            except (InvalidToken, json.JSONDecodeError, UnicodeDecodeError):
                return None

            account = payload.get("account") if isinstance(payload.get("account"), dict) else None
            created_at = float(payload.get("created_at", time.time()))
            updated_at = float(payload.get("updated_at", created_at))

            try:
                token = Token.from_dict(token_data)
            except Exception:
                return None

            return SeedrTokenRecord(token=token, account=account, created_at=created_at, updated_at=updated_at)

    def save_token(self, token: Token, account: Optional[Dict[str, Any]] = None) -> None:
        serialized = json.dumps(token.to_dict(), ensure_ascii=False).encode("utf-8")
        encrypted = self._fernet.encrypt(serialized).decode("utf-8")

        existing = self.load_token()
        created_at = existing.created_at if existing else time.time()
        payload = {
            "token": encrypted,
            "account": account or {},
            "created_at": created_at,
            "updated_at": time.time(),
        }

        temp_path = f"{self.token_path}.tmp"
        with self._lock:
            with open(temp_path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
            os.replace(temp_path, self.token_path)
            if os.path.exists(self.challenge_path):
                os.remove(self.challenge_path)

    def clear_token(self) -> None:
        with self._lock:
            if os.path.exists(self.token_path):
                try:
                    os.remove(self.token_path)
                except OSError:
                    pass

    # ------------------------------------------------------------------
    # Device authorization challenge handling
    # ------------------------------------------------------------------
    def save_device_challenge(self, challenge: Dict[str, Any]) -> None:
        temp_path = f"{self.challenge_path}.tmp"
        with self._lock:
            with open(temp_path, "w", encoding="utf-8") as fh:
                json.dump({"challenge": challenge, "created_at": time.time()}, fh)
            os.replace(temp_path, self.challenge_path)

    def load_device_challenge(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            if not os.path.exists(self.challenge_path):
                return None
            try:
                with open(self.challenge_path, "r", encoding="utf-8") as fh:
                    payload = json.load(fh)
            except (OSError, json.JSONDecodeError):
                return None

        challenge = payload.get("challenge")
        if not isinstance(challenge, dict):
            return None
        challenge.setdefault("created_at", payload.get("created_at", time.time()))
        return challenge

    def clear_device_challenge(self) -> None:
        with self._lock:
            if os.path.exists(self.challenge_path):
                try:
                    os.remove(self.challenge_path)
                except OSError:
                    pass

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        record = self.load_token()
        if not record:
            challenge = self.load_device_challenge()
            return {
                "connected": False,
                "account": None,
                "device_challenge": challenge,
            }

        return {
            "connected": True,
            "account": record.account or {},
            "token_created_at": record.created_at,
            "token_updated_at": record.updated_at,
        }

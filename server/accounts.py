"""Server-side account store backed by a JSON config file.

The file is reloaded automatically when its mtime changes, so editing it takes
effect without restarting the server.  Example::

    {
      "users": [
        {"name": "alice", "password": "alice-secret"},
        {"name": "bob",   "password_hash": "pbkdf2_sha256$200000$...$..."}
      ]
    }

``password`` is plaintext (convenient); ``password_hash`` is preferred and can
be produced with ``pfs.server.hash_password`` (see ``scripts/hash_password.py``).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path

PBKDF2_ITERATIONS = 200_000
_HERE = Path(__file__).resolve().parent
DEFAULT_ACCOUNTS = _HERE / "accounts.json"
EXAMPLE_ACCOUNTS = _HERE / "accounts.example.json"


def hash_password(password: str, *, iterations: int = PBKDF2_ITERATIONS) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256${}${}${}".format(
        iterations,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(dk).decode("ascii"),
    )


def verify_password_hash(password: str, encoded: str) -> bool:
    try:
        algo, iterations, salt_b64, hash_b64 = encoded.split("$")
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(dk, expected)
    except (ValueError, TypeError):
        return False


class AccountStore:
    def __init__(self, path: str | os.PathLike | None = None):
        chosen = path or os.environ.get("PFS_ACCOUNTS") or DEFAULT_ACCOUNTS
        self.path = Path(chosen)
        self._users: dict[str, dict] = {}
        self._mtime: float | None = None
        self.reload(force=True)

    def reload(self, force: bool = False) -> None:
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            self._users = {}
            self._mtime = None
            return
        if not force and mtime == self._mtime:
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._users = {}
            self._mtime = mtime
            return
        users: dict[str, dict] = {}
        for item in data.get("users", []):
            name = str(item.get("name", "")).strip()
            if name:
                users[name] = item
        self._users = users
        self._mtime = mtime

    def names(self) -> list[str]:
        self.reload()
        return sorted(self._users)

    def verify(self, name: str, password: str) -> bool:
        self.reload()
        user = self._users.get(name)
        if user is None:
            return False
        if "password_hash" in user:
            return verify_password_hash(password, str(user["password_hash"]))
        return hmac.compare_digest(str(user.get("password", "")), password)

"""Generate a PBKDF2 password hash for server/accounts.json.

Usage::

    python scripts/hash_password.py [password]

If no password is given it is prompted for.
"""

from __future__ import annotations

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.accounts import hash_password  # noqa: E402


def main() -> int:
    if len(sys.argv) > 1:
        password = sys.argv[1]
    else:
        password = getpass.getpass("password: ")
        if password != getpass.getpass("repeat: "):
            print("passwords do not match")
            return 1
    print(hash_password(password))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

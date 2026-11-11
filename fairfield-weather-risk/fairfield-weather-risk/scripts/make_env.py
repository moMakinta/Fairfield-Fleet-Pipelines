"""Creates .env from .env.example with random secrets, so no password is ever written by hand or committed.

    python scripts/make_env.py

It refuses to overwrite an existing .env, because the passwords in it are the
ones the databases were created with. Changing them afterwards locks you out.
Only the standard library is used, so this runs before anything is installed.
"""
from __future__ import annotations

import base64
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDER = "CHANGE_ME"


def fernet_key() -> str:
    """A Fernet key is 32 random bytes in URL-safe base64. Airflow uses it to encrypt stored passwords."""
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


def main() -> int:
    target = ROOT / ".env"
    if target.exists():
        print(".env already exists, leaving it alone. Delete it first if you really want a new one "
              "(and run 'docker compose down -v', because the old passwords are baked into the databases).")
        return 1

    lines = []
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if line.startswith("FERNET_KEY="):
            line = f"FERNET_KEY={fernet_key()}"
        elif line.endswith(f"={PLACEHOLDER}"):
            # token_hex gives letters and digits only, which is safe inside a connection URL
            line = line.replace(PLACEHOLDER, secrets.token_hex(16))
        lines.append(line)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")

    values = dict(line.split("=", 1) for line in lines if "=" in line and not line.startswith("#"))
    print("Created .env")
    print(f"  Airflow login:      {values['_AIRFLOW_WWW_USER_USERNAME']} / {values['_AIRFLOW_WWW_USER_PASSWORD']}")
    print(f"  Warehouse (psql, DBeaver, Excel): localhost:{values['WAREHOUSE_PORT']}  database {values['WAREHOUSE_DB']}  "
          f"user {values['WAREHOUSE_USER']}  password {values['WAREHOUSE_PASSWORD']}")
    print("These are also in the .env file if you need them again.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

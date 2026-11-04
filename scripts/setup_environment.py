"""Create local credentials without printing them or overwriting existing configuration."""

import os
from pathlib import Path
import secrets

from cryptography.fernet import Fernet

root = Path(__file__).resolve().parents[1]
target = root / ".env"
content = (root / ".env.example").read_text()
for name in ("OWNER_TOKEN", "AGENT_TOKEN", "GRANT_SECRET"):
    content = content.replace(name + "=\n", name + "=" + secrets.token_urlsafe(48) + "\n", 1)
content = content.replace("DATA_KEY=\n", "DATA_KEY=" + Fernet.generate_key().decode() + "\n", 1)
try:
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
except FileExistsError:
    print(".env already exists; left it unchanged.")
else:
    with os.fdopen(fd, "w") as out:
        out.write(content)
    print(
        "Created private .env. Open it locally to configure providers and copy OWNER_TOKEN into the dashboard."
    )
    print(
        "Give only AGENT_TOKEN to your agent. Keep OWNER_TOKEN and provider credentials in the trusted process."
    )

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import get_config, normalize_ssh_config


cfg = normalize_ssh_config(get_config().get("ssh", {}))
print({key: value for key, value in cfg.items() if key != "password_ref"})
print("has_password_ref", bool(cfg.get("password_ref")))

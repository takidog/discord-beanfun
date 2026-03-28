import os
from pathlib import Path


def _load_local_config() -> dict[str, str]:
    """Load key-value pairs from local config file if it exists."""
    repo_root = Path(__file__).resolve().parents[2]
    config_path = repo_root / "config"
    if not config_path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in config_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


_LOCAL_CONFIG = _load_local_config()


def _get_config(key: str, default=None):
    if key in _LOCAL_CONFIG:
        return _LOCAL_CONFIG[key]
    return os.environ.get(key, default)


# Guild: Server id.
LIMIT_GUILD = [guild_id for guild_id in _get_config("LIMIT_GUILD", "").split(",") if guild_id]

BOT_TOKEN = _get_config("BOT_TOKEN", None)

LOGIN_TIME_OUT = int(_get_config("LOGIN_TIME_OUT", 180))

OTP_DISPLAY_TIME = int(_get_config("OTP_DISPLAY_TIME", 20))

HIDDEN_PRIVATE_MESSAGE = bool(int(_get_config("HIDDEN_PRIVATE_MESSAGE", 1)))

REDIRECT_URL = _get_config("REDIRECT_URL", False)

_feat_app_server_raw = _get_config("FEAT_APP_SERVER", "0").strip().lower()
FEAT_APP_SERVER = _feat_app_server_raw in ("1", "true")

API_PORT = int(_get_config("API_PORT", 8080))

DB_PATH = _get_config("DB_PATH", "./data/tokens.db")
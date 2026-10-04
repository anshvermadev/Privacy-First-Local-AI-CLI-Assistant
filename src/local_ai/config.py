"""Strict policy parsing: malformed policy never grants cloud permission."""
from copy import deepcopy
import json
import os
from pathlib import Path

from .models import SafeError

FLAGS = ("cloud_ai_enabled", "send_personal_data_to_cloud", "send_confidential_data_to_cloud", "send_secret_data_to_cloud")
DEFAULTS = {
    **dict.fromkeys(FLAGS, False),
    "raw_retention_days": 7, "audit_retention_days": 90,
    "deny_apps": ["1Password", "Bitwarden", "KeePass", "Keychain Access"],
    "deny_sources": ["ssh-add", "keychain"],
    "public_sources": ["https://docs.python.org", "https://developer.mozilla.org"],
    "people": [], "projects": {}, "customer_names": [],
    "local_model": None,
}


def data_dir():
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "local-ai"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "local-ai"


def validate_settings(obj):
    if not isinstance(obj, dict) or set(obj) - set(DEFAULTS):
        raise SafeError("Settings contain unknown keys or are not an object.", "INVALID_SETTINGS")
    result = deepcopy(DEFAULTS)
    for key, value in obj.items():
        if key in FLAGS and type(value) is not bool:
            raise SafeError("Cloud policy flags must be JSON booleans.", "INVALID_SETTINGS")
        if key.endswith("_retention_days") and (type(value) is not int or not 1 <= value <= 3650):
            raise SafeError("Retention must be between 1 and 3650 days.", "INVALID_SETTINGS")
        if isinstance(DEFAULTS[key], list):
            if not isinstance(value, list) or len(value) > 1000 or any(not isinstance(x, str) or not x.strip() or len(x) > 256 for x in value):
                raise SafeError("Settings lists must contain bounded, nonempty strings.", "INVALID_SETTINGS")
        if key == "projects" and (not isinstance(value, dict) or len(value) > 1000 or any(not isinstance(k, str) or not k or not isinstance(v, str) or not v or max(len(k), len(v)) > 256 for k, v in value.items())):
            raise SafeError("Projects must map aliases to names.", "INVALID_SETTINGS")
        if key == "local_model" and value is not None and (not isinstance(value, str) or not value.strip() or len(value) > 128):
            raise SafeError("Local model must be null or a model name.", "INVALID_SETTINGS")
        result[key] = value
    return result


def load_settings(path):
    try:
        if path.stat().st_size > 262144:
            raise ValueError()
        return validate_settings(json.loads(path.read_text(encoding="utf-8"))), True
    except (OSError, ValueError, SafeError, RecursionError):
        return deepcopy(DEFAULTS), False

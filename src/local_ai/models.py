"""Validated boundary types. Errors never include input values."""
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import IntEnum
import re
import unicodedata


class SafeError(Exception):
    def __init__(self, message, code="INVALID_INPUT"):
        super().__init__(message)
        self.code = code


class Tier(IntEnum):
    public = 0
    personal = 1
    confidential = 2
    secret = 3

    @classmethod
    def parse(cls, value):
        try:
            return cls[value]
        except (KeyError, TypeError):
            raise SafeError("Unknown sensitivity tier.") from None


TYPES = {"transcript", "note", "shell_history", "browser_metadata", "clipboard"}
FIELDS = {"type", "app", "source", "content", "timestamp"}


def utc_timestamp(value, *, future_allowed=False):
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)", value
    ):
        raise SafeError("Timestamp must be ISO 8601 UTC (ending Z or +00:00).")
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise SafeError("Invalid timestamp.") from None
    if not future_allowed and date > datetime.now(timezone.utc):
        raise SafeError("Future event timestamps are not accepted.")
    return int(date.timestamp())


def sanitize(text):
    text = unicodedata.normalize("NFKC", text)
    return "".join(c for c in text if c in "\n\t" or not unicodedata.category(c).startswith("C"))


def injection_suspected(text):
    return bool(re.search(
        r"ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions|<\|(?:system|assistant|im_start)\|>|"
        r"(?:^|\n)\s*(?:system|developer)\s*:|reveal\s+(?:the\s+)?(?:secrets|system prompt)|"
        r"disregard\s+(?:the\s+)?(?:policy|instructions)", text, re.I
    ))


@dataclass(frozen=True)
class Event:
    type: str
    app: str
    source: str
    content: str
    timestamp: str
    event_ts: int

    @classmethod
    def validate(cls, obj):
        if not isinstance(obj, dict) or set(obj) != FIELDS:
            raise SafeError("Event must contain exactly type, app, source, content, timestamp.", "INVALID_EVENT")
        if any(not isinstance(v, str) for v in obj.values()):
            raise SafeError("All event fields must be strings.", "INVALID_EVENT")
        if obj["type"] not in TYPES:
            raise SafeError("Unsupported event type.", "INVALID_EVENT")
        for key, cap in (("content", 32768), ("app", 256), ("source", 2048)):
            if not obj[key].strip() or len(obj[key].encode("utf-8")) > cap:
                raise SafeError("An event field is empty or exceeds its size limit.", "INVALID_EVENT")
        ts = utc_timestamp(obj["timestamp"])
        clean = {k: sanitize(v) for k, v in obj.items()}
        if any(not v.strip() for v in clean.values()):
            raise SafeError("An event field is empty after sanitization.", "INVALID_EVENT")
        return cls(**clean, event_ts=ts)


def duration(value):
    match = re.fullmatch(r"([1-9]\d*)([mhdw])", value or "")
    if not match:
        raise SafeError("Duration must be a positive number followed by m, h, d or w.")
    return int(match[1]) * {"m": 60, "h": 3600, "d": 86400, "w": 604800}[match[2]]

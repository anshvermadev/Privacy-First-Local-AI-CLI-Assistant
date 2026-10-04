"""Diagnostic logger accepts only event codes and validated UUIDs."""
import logging
import uuid


def log_event(code, event_id=None):
    if code not in {"ingest_ok", "ingest_rejected", "search_ok", "storage_error", "route_blocked"}:
        code = "storage_error"
    try:
        identifier = str(uuid.UUID(event_id)) if event_id else "-"
    except (ValueError, TypeError, AttributeError):
        identifier = "-"
    logging.getLogger("local_ai").info("%s event_id=%s", code, identifier)

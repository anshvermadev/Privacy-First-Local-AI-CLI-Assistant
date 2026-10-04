"""Validate/classify/redact before persistence. Batch writes are atomic."""
from collections import Counter
import json
import re
import uuid

from .classify import classify
from .extract import extract, safe_memory
from .local_model import enhance
from .models import Event, SafeError, Tier
from .redact import redact
from .route import route
from .store import transaction, insert, audit

MAX_INPUT = 8 * 1024 * 1024


def decode_events(data):
    if len(data) > MAX_INPUT:
        raise SafeError("Input exceeds 8 MiB limit.")
    try:
        obj = json.loads(data)
    except (ValueError, RecursionError):
        raise SafeError("Input is not valid JSON.") from None
    if isinstance(obj, dict):
        obj = [obj]
    if not isinstance(obj, list) or len(obj) > 10000:
        raise SafeError("Input must be an event object or array of at most 10000 events.")
    return obj


def ingest(root, events, settings, settings_valid, vault=None, *, dry_run=False, drop_secrets=False):
    prepared, errors, dropped = [], [], 0
    for index, obj in enumerate(events):
        try:
            event = Event.validate(obj)
            if any(x.casefold() in event.app.casefold() for x in settings["deny_apps"]) or any(x.casefold() in event.source.casefold() for x in settings["deny_sources"]) or (event.type == "shell_history" and re.search(r"(?:^|[;&|]\s*)(?:sudo\s+)?(?:ssh-add|security\s+(?:add|find)-generic-password)\b", event.content)):
                dropped += 1
                continue
            try:
                result = classify(event.content, event.app, event.source, settings)
            except Exception:
                # Reject rather than extract potentially unredactable content.
                raise SafeError("Classification failed; event was not stored.", "CLASSIFICATION_FAILED") from None
            if drop_secrets and result["contains_secret_value"]:
                dropped += 1
                continue
            memory = extract(event, result, settings)
            if settings["local_model"] and not dry_run:
                memory, result, _ = enhance(event, memory, result, settings["local_model"])
            memory = safe_memory(memory)
            # Reclassify derived text too: aliases/model output may introduce
            # sensitive data independently of the original content.
            derived = classify(json.dumps(memory), source=event.source, settings=settings)
            if Tier.parse(derived["tier"]) > Tier.parse(result["tier"]):
                result["tier"] = derived["tier"]
                result["matched_rules"] += derived["matched_rules"]
                result["explanation"] += "; derived memory raises sensitivity"
            result["contains_secret_value"] |= derived["contains_secret_value"]
            memory["sensitivity"] = result["tier"]
            count = redact("\n".join((event.content, event.app, event.source)))[1]
            verdict = route([result["tier"]], settings, settings_valid=settings_valid, redactions_required=count)
            prepared.append((event, memory, result, verdict))
        except SafeError as exc:
            errors.append({"event_index": index, "code": exc.code, "message": str(exc)})
    batch_id = str(uuid.uuid4())
    ids, duplicates, tiers = [], 0, Counter()
    if not dry_run:
        if vault is None:
            raise SafeError("Raw storage is locked.", "KEY_UNAVAILABLE")
        with transaction(root) as db:
            for event, memory, result, verdict in prepared:
                memory_id = insert(db, event, memory, result, vault, batch_id, settings)
                if memory_id is None:
                    duplicates += 1
                else:
                    ids.append(memory_id)
                    tiers[result["tier"]] += 1
                    audit(db, verdict, settings, "ingest")
    else:
        tiers.update(result["tier"] for _, _, result, _ in prepared)
    aggregate = route([result["tier"] for _, _, result, _ in prepared] + (["invalid"] if errors else []), settings,
                      settings_valid=settings_valid, redactions_required=sum(v["redactions_required"] for _, _, _, v in prepared))
    output = {"batch_id": batch_id, "accepted": len(prepared) if dry_run else len(ids), "duplicates": duplicates,
              "dropped": dropped, "rejected": len(errors), "errors": errors, "tiers": dict(tiers),
              "memory_ids": ids, "dry_run": dry_run, "verdict": aggregate}
    if dry_run:
        output["preview"] = [memory for _, memory, _, _ in prepared]
    return output

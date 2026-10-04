"""Payload preparation only. The assignment requires verdicts, not cloud calls."""
from .classify import classify
from .models import SafeError, Tier
from .redact import redact
from .route import route


def prepare_payload(memories, settings, *, settings_valid=True):
    tiers, payload, count = [], [], 0
    for memory in memories:
        # Defense in depth: never trust stored tier labels alone at egress.
        text = memory["summary"] + "\n" + "\n".join(memory["topics"])
        detected = classify(text, settings=settings)
        tiers.extend([memory["sensitivity"], detected["tier"]])
        summary, n = redact(memory["summary"], memory.get("people", []))
        count += n
        topics = []
        for topic in memory["topics"]:
            safe, n = redact(topic, memory.get("people", []))
            topics.append(safe)
            count += n
        payload.append({"summary": summary, "topics": topics, "tier": max(Tier.parse(memory["sensitivity"]), Tier.parse(detected["tier"])).name})
    verdict = route(tiers, settings, "cloud_required", settings_valid=settings_valid, redactions_required=count)
    if verdict["path"] != "cloud_ai":
        raise SafeError("Cloud policy denies payload preparation.", "BLOCKED")
    return {"memories": payload}, verdict


def send(*args, **kwargs):
    raise SafeError("Cloud transport is intentionally unavailable in this local prototype.", "BLOCKED")

"""Deterministic extraction over redacted content, with configurable aliases."""
import re
from .redact import redact
from .models import sanitize

TOPICS = {"stripe": "Stripe", "payment intent": "Payment Intent", "backend": "Backend Security",
          "roadmap": "Roadmap", "marketing": "Marketing", "press release": "Press Releases",
          "patient": "Healthcare", "blood pressure": "Blood Pressure", "python": "Python",
          "deployment": "Deployment", "database": "Database", "security": "Security"}


def extract(event, classification, settings):
    text, _ = redact(event.content)
    people = set(re.findall(r"\b([A-Z][a-z]{1,30}(?: [A-Z][a-z]{1,30})?)\s+(?:said|says|asked|suggested|reviewed|decided)\b", text))
    people.update(n for n in settings["people"] if re.search(r"(?<!\w)" + re.escape(n) + r"(?!\w)", text, re.I))
    aliases = {"pricing page": "Pricing Page", **settings["projects"]}
    projects = {name for alias, name in aliases.items() if alias.lower() in text.lower()}
    projects.update(m.title() for m in re.findall(r"\bproject\s+([A-Z][A-Za-z0-9_-]+)", text))
    topics = [name for needle, name in TOPICS.items() if needle in text.lower()]
    summary = " ".join(re.split(r"(?<=[.!?])\s+", text.strip())[:2])[:1000]
    return {"people": sorted(people), "projects": sorted(projects), "topics": topics,
            "summary": summary, "sensitivity": classification["tier"]}


def safe_memory(memory):
    return {key: [redact(sanitize(x))[0] for x in value] if isinstance(value, list) else redact(sanitize(value))[0]
            for key, value in memory.items()}

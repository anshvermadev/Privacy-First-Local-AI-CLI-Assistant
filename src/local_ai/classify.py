"""Deterministic highest-tier classifier with a conservative unknown default."""
import re
from urllib.parse import urlsplit

from .models import Tier, injection_suspected
from .redact import spans

VERSION = "1.0.0"


def is_public(source, allowlist):
    for entry in allowlist:
        if source.casefold() == entry.casefold():
            return True
        a, b = urlsplit(source), urlsplit(entry)
        if a.scheme == b.scheme == "https" and a.hostname and a.hostname == b.hostname and a.port == b.port and not a.username and not a.password:
            path = b.path.rstrip("/")
            if not path or a.path == path or a.path.startswith(path + "/"):
                return True
    return False


def classify(content, app="", source="", settings=None):
    settings = settings or {}
    text = "\n".join((content, app, source))
    rules = []

    def add(rule, tier, evidence):
        rules.append({"rule": rule, "tier": tier, "evidence": evidence})

    detected = spans(text)
    for label, secret in sorted({(h[2], h[3]) for h in detected}):
        add("value." + label.lower(), "secret" if secret else "personal", "Detected " + label.lower().replace("_", " "))
    if re.search(r"\b(?:secret\s+keys?|api\s+keys?|private\s+keys?|passwords?|credentials?|secret\s+tokens?)\b", text, re.I):
        add("keyword.secret_key_mention", "secret", "Credential topic (may not contain a value)")
    medical = bool(re.search(r"\b(?:patient|medical|diagnostics?|heart\s+rate|blood\s+pressure|health|diagnosis)\b", text, re.I))
    if medical or re.search(r"\b(?:private\s+(?:chat|conversation)|passport|identity\s+document)\b", text, re.I):
        add("context.personal", "personal", "Medical, identity or private conversation context")
    # The assignment's medical Internal Portal example is personal. Business
    # keywords still raise it; a generic portal label alone does not.
    business = re.search(r"\b(?:roadmap|revenue|Q[1-4]|unreleased|proprietary|pricing|financial)\b", text, re.I) or re.search(r"\binternal\b", content + "\n" + app, re.I)
    internal_source = source.lower().startswith("internal") and not medical
    customer = any(re.search(r"(?<!\w)" + re.escape(n) + r"(?!\w)", text, re.I) for n in settings.get("customer_names", []))
    if business or internal_source or customer:
        add("context.business", "confidential", "Internal business plans, metrics or customer context")
    if not rules:
        public = is_public(source, settings.get("public_sources", []))
        add("source.public_allowlist" if public else "default.unknown", "public" if public else "personal", "Explicit public source" if public else "Unknown context stays private")
    tier = max(Tier.parse(r["tier"]) for r in rules).name
    return {"tier": tier, "confidence": 0.95 if detected else 0.8 if tier != "personal" else 0.65,
            "explanation": "; ".join(r["evidence"] for r in rules if r["tier"] == tier),
            "matched_rules": rules, "contains_secret_value": any(h[3] for h in detected),
            "injection_suspected": injection_suspected(text), "classifier_version": VERSION}

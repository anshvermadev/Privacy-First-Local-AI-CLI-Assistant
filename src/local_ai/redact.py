"""Shared detection/redaction rules. Evidence contains labels, never matches."""
from collections import Counter
import math
import re

PATTERNS = [
    ("PRIVATE_KEY", r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----[\s\S]*?(?:-----END (?:[A-Z0-9]+ )*PRIVATE KEY-----|\Z)", True),
    ("API_KEY", r"\b(?:sk_(?:live|test)_[A-Za-z0-9_]+|sk-[A-Za-z0-9_-]{12,}|AKIA[A-Z0-9]{16}|gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+|xox[baprs]-[A-Za-z0-9-]+)\b", True),
    ("CREDENTIAL", r"\b(?:password|passwd|pwd|api[_ -]?key|secret[_ -]?key|access[_ -]?token|token|client[_ -]?secret)[\"']?\s*[:=]\s*(?:\"[^\"\n]+\"|'[^'\n]+'|[^\s,;]+)", True),
    ("CREDENTIAL", r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|https?)://[^\s/@:]+:[^\s/@]+@[^\s]+", True),
    ("TOKEN", r"\bBearer\s+[A-Za-z0-9._~+/-]+=*", True),
    ("JWT", r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", True),
    ("EMAIL", r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", False),
    ("ID", r"\b\d{3}-\d{2}-\d{4}\b|\b(?:patient\s+)?ID\s*[:#]?\s*[A-Z0-9]+(?:-[A-Z0-9]+)+\b", False),
    ("PHONE", r"(?<!\w)(?:\+\d{1,3}[ .-]?)?(?:\(\d{3}\)|\d{3})[ .-]\d{3}[ .-]\d{4}(?!\w)", False),
]
COMPILED = [(label, re.compile(pattern, re.I if label != "API_KEY" else 0), secret) for label, pattern, secret in PATTERNS]


def entropy(value):
    return -sum((count / len(value)) * math.log2(count / len(value)) for count in Counter(value).values())


def luhn(value):
    digits = [int(x) for x in value if x.isdigit() and x.isascii()]
    if not 13 <= len(digits) <= 19 or len(set(digits)) < 2:
        return False
    return sum((2*d - 9 if 2*d > 9 else 2*d) if i % 2 else d for i, d in enumerate(reversed(digits))) % 10 == 0


def spans(text):
    hits = []
    for label, pattern, secret in COMPILED:
        hits.extend((m.start(), m.end(), label, secret) for m in pattern.finditer(text))
    for m in re.finditer(r"(?<!\w)(?:\d[ -]?){12,18}\d(?!\w)", text):
        if luhn(m[0]):
            hits.append((m.start(), m.end(), "PAYMENT_CARD", True))
    for m in re.finditer(r"\b[A-Za-z0-9_+/=-]{24,}\b", text):
        value = m[0]
        if any(c.isalpha() for c in value) and any(c.isdigit() for c in value) and entropy(value) >= 4.0:
            hits.append((m.start(), m.end(), "HIGH_ENTROPY_TOKEN", True))
    return hits


def redact(text, names=()):
    hits = spans(text)
    for name in names:
        if name:
            hits.extend((m.start(), m.end(), "PERSON", False) for m in re.finditer(r"(?<!\w)" + re.escape(name) + r"(?!\w)", text, re.I))
    # Merge overlaps so partially overlapping detectors cannot leave token suffixes.
    merged = []
    for start, end, label, secret in sorted(hits, key=lambda h: (h[0], -h[1])):
        if merged and start < merged[-1][1]:
            prior = merged[-1]
            merged[-1] = (prior[0], max(end, prior[1]), prior[2], prior[3] or secret)
        else:
            merged.append((start, end, label, secret))
    for start, end, label, _ in reversed(merged):
        text = text[:start] + "[REDACTED:" + label + "]" + text[end:]
    return text, len(merged)

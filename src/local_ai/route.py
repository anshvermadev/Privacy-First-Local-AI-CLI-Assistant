"""Pure routing function; cloud eligibility is not a network operation."""
from .config import FLAGS, validate_settings
from .models import Tier, SafeError


def route(tiers, settings, mode="auto", *, settings_valid=True, redactions_required=0):
    if mode not in ("auto", "cloud_required"):
        raise SafeError("Unknown routing mode.")
    valid = settings_valid
    try:
        settings = validate_settings(settings)
        maximum = max((Tier.parse(t) for t in tiers), default=Tier.personal)
    except SafeError:
        maximum = Tier.secret
        settings = dict.fromkeys(FLAGS, False)
        valid = False
    tier = maximum.name
    flag = "send_" + tier + "_data_to_cloud"
    allowed = valid and settings["cloud_ai_enabled"] and (tier == "public" or settings[flag])
    path = "cloud_ai" if allowed else "blocked" if mode == "cloud_required" else "local_ai"
    reasons = ["max tier is " + tier]
    if not valid:
        reasons.append("Settings or classification invalid; cloud denied")
    elif not settings["cloud_ai_enabled"]:
        reasons.append("cloud_ai_enabled is false")
    elif tier != "public":
        reasons.append(flag + " is " + str(settings[flag]).lower())
    reasons.append({"cloud_ai": "Cloud eligible only after redaction; no request sent",
                    "local_ai": "Using local processing", "blocked": "Required cloud path is denied"}[path])
    verdict = {"path": path, "max_tier": tier, "mode": mode,
               "settings_evaluated": {k: settings[k] for k in FLAGS if k == "cloud_ai_enabled" or k == flag},
               "reasons": reasons, "redactions_required": redactions_required}
    if tier == "secret" and allowed:
        verdict["warning"] = "Secret values must always be redacted, even with consent."
    return verdict

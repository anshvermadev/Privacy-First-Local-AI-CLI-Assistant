"""Read-only storage, permissions and policy diagnostics."""
import json
from .config import load_settings
from .permissions import permission_status
from .store import connect


def doctor(root):
    checks = []
    _, valid = load_settings(root / "settings.json")
    checks.append({"check": "settings", "ok": valid})
    try:
        permissions = permission_status(root)
    except Exception:
        permissions = False
    checks.append({"check": "owner_only_permissions", "ok": permissions})
    for name in ("raw", "memories", "audit"):
        try:
            db = connect(root / (name + ".db"), readonly=True)
            try:
                ok = db.execute("PRAGMA integrity_check").fetchone()[0] == "ok" and not db.execute("PRAGMA foreign_key_check").fetchall()
                if name == "memories":
                    ok = ok and db.execute("SELECT count(*) FROM memories").fetchone()[0] == db.execute("SELECT count(*) FROM memory_fts").fetchone()[0]
            finally:
                db.close()
        except Exception:
            ok = False
        checks.append({"check": name + "_integrity", "ok": ok})
    try:
        obj = json.loads((root / "crypto.json").read_text(encoding="utf-8"))
        mode = obj["mode"]
        ok = mode in ("none", "passphrase", "keyring") and obj["version"] == 1
        if mode == "keyring":
            import keyring
            ok = ok and bool(keyring.get_password("privacy-first-local-ai", obj["account"]))
        if mode == "passphrase":
            ok = ok and bool(obj["salt"]) and bool(obj["wrapped"])
    except Exception:
        mode, ok = "unknown", False
    checks.append({"check": "key_metadata", "ok": ok, "mode": mode,
                   "note": "Passphrase decryption verified only when ingest unlocks storage; memory index is redacted plaintext."})
    return {"ok": all(c["ok"] for c in checks), "checks": checks, "encryption": mode,
            "network": "No cloud transport; optional Ollama connects only to 127.0.0.1:11434"}

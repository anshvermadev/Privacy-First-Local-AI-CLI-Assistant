"""Explicit lifecycle operations with FTS and entity cleanup."""
import time

from .models import SafeError, Tier, sanitize
from .redact import redact
from .store import transaction, connect
from .crypto import remove_key
from .permissions import check_state, MARKER


def orphan_cleanup(db):
    db.execute("DELETE FROM entities WHERE id NOT IN (SELECT entity_id FROM memory_entities)")


def compact(root):
    for name in ("raw", "memories", "audit"):
        db = connect(root / (name + ".db"))
        try:
            if name == "memories":
                db.execute("INSERT INTO memory_fts(memory_fts) VALUES('optimize')")
                db.commit()
            db.execute("VACUUM")
        finally:
            db.close()


def forget(root, since=None, until=None, batch=None, memory_id=None, all_memories=False):
    if memory_id:
        clause, values = "id=?", [memory_id]
    elif all_memories:
        clause, values = "1=1", []
    elif batch:
        clause, values = "batch_id=?", [batch]
    elif since is not None:
        until = int(time.time()) if until is None else until
        if since > until:
            raise SafeError("Start time must not be later than end time.")
        clause, values = "event_ts>=? AND event_ts<=?", [since, until]
    else:
        raise SafeError("Specify --id, --all, --last, --since or --batch.")
    with transaction(root) as db:
        if memory_id:
            row = db.execute("SELECT source_event_id FROM memories WHERE id=?", (memory_id,)).fetchone()
            if row is None:
                raise SafeError("Memory not found.", "NOT_FOUND")
            raw = db.execute("DELETE FROM raw.raw_events WHERE id=?", (row[0],)).rowcount
        else:
            raw = db.execute("DELETE FROM raw.raw_events WHERE " + clause, values).rowcount
        memories = db.execute("DELETE FROM memories WHERE " + clause, values).rowcount
        orphan_cleanup(db)
        db.execute("INSERT INTO audit.deletion_log(ts,scope,rows_deleted) VALUES(?,?,?)", (int(time.time()), "memory" if memory_id else "all" if all_memories else "batch" if batch else "time_range", memories + raw))
    compact(root)
    return {"memories_deleted": memories, "raw_events_deleted": raw}


def maintain(root, settings):
    now = int(time.time())
    with transaction(root) as db:
        raw = db.execute("DELETE FROM raw.raw_events WHERE expires_ts<=?", (now,)).rowcount
        audit = db.execute("DELETE FROM audit.routing_audit WHERE ts<?", (now - settings["audit_retention_days"] * 86400,)).rowcount
        db.execute("DELETE FROM audit.deletion_log WHERE ts<?", (now - settings["audit_retention_days"] * 86400,))
        orphan_cleanup(db)
    compact(root)
    return {"expired_raw_deleted": raw, "expired_audit_deleted": audit, "optimized": True}


def reclassify(root, memory_id, tier, reason, confirm_lower=False):
    new = Tier.parse(tier)
    if not reason or not reason.strip() or len(reason) > 1000:
        raise SafeError("A reason of 1 to 1000 characters is required.")
    with transaction(root) as db:
        row = db.execute("SELECT sensitivity FROM memories WHERE id=?", (memory_id,)).fetchone()
        if row is None:
            raise SafeError("Memory not found.", "NOT_FOUND")
        if new < Tier.parse(row[0]) and not confirm_lower:
            raise SafeError("Lowering sensitivity requires --confirm-lower.", "CONFIRMATION_REQUIRED")
        db.execute("UPDATE memories SET sensitivity=?,user_override=? WHERE id=?", (tier, tier, memory_id))
        db.execute("INSERT INTO corrections(memory_id,ts,old_tier,new_tier,reason) VALUES(?,?,?,?,?)",
                   (memory_id, int(time.time()), row[0], tier, redact(sanitize(reason))[0]))
    return {"id": memory_id, "sensitivity": tier, "changed_from": row[0]}


def wipe(root):
    root = check_state(root)
    # No recursive delete. Refuse unrelated files; protect user-selected paths.
    allowed = {MARKER, "settings.json", "crypto.json", "raw.db", "memories.db", "audit.db"}
    paths = list(root.iterdir())
    if any(p.name not in allowed or not p.is_file() or p.is_symlink() for p in paths):
        raise SafeError("Data directory contains unexpected files; wipe refused.", "UNSAFE_PATH")
    remove_key(root)
    for path in paths:
        path.unlink()
    root.rmdir()
    return {"wiped": True}

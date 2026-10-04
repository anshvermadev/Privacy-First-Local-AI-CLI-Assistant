"""Bounded FTS5 BM25 search; this module never opens raw.db."""
import re
from .models import SafeError
from .store import connect, hydrate


def search(root, query, limit=20, since=None, tier=None):
    if not isinstance(query, str) or not query.strip() or len(query.encode("utf-8")) > 4096:
        raise SafeError("Search query must be nonempty and at most 4096 bytes.")
    if not 1 <= limit <= 100:
        raise SafeError("Search limit must be between 1 and 100.")
    terms = re.findall(r"\w+", query, re.UNICODE)[:64]
    if not terms:
        return []
    fts = " AND ".join('"' + t.replace('"', '""') + '"' for t in terms)
    sql = "SELECT m.* FROM memory_fts JOIN memories m ON m.rowid=memory_fts.rowid WHERE memory_fts MATCH ?"
    args = [fts]
    if since is not None:
        sql += " AND event_ts>=?"
        args.append(since)
    if tier:
        sql += " AND sensitivity=?"
        args.append(tier)
    sql += " ORDER BY bm25(memory_fts),event_ts DESC LIMIT ?"
    args.append(limit)
    db = connect(root / "memories.db", readonly=True)
    try:
        return [hydrate(db, row) for row in db.execute(sql, args)]
    finally:
        db.close()


def show(root, memory_id, explain=False):
    db = connect(root / "memories.db", readonly=True)
    try:
        row = db.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
        if row is None:
            raise SafeError("Memory not found.", "NOT_FOUND")
        return hydrate(db, row, explain)
    finally:
        db.close()


def recent(root, limit=10):
    """Newest memories, without crossing into raw storage."""
    if not 1 <= limit <= 100:
        raise SafeError("Search limit must be between 1 and 100.")
    db = connect(root / "memories.db", readonly=True)
    try:
        return [hydrate(db, row) for row in db.execute("SELECT * FROM memories ORDER BY event_ts DESC,rowid DESC LIMIT ?", (limit,))]
    finally:
        db.close()

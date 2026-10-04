"""SQLite trust zones, versioned schema, atomic attached-database writes."""
from contextlib import contextmanager
import hashlib
import json
import sqlite3
import time
import uuid

from .models import SafeError
from .permissions import secure

SCHEMA_VERSION = 1
SCHEMAS = {
"memories": """
CREATE TABLE memories (
 rowid INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL, source_event_id TEXT UNIQUE NOT NULL,
 batch_id TEXT NOT NULL, event_ts INTEGER NOT NULL, created_ts INTEGER NOT NULL,
 content_hash TEXT NOT NULL, summary TEXT NOT NULL,
 sensitivity TEXT NOT NULL CHECK(sensitivity IN ('public','personal','confidential','secret')),
 confidence REAL NOT NULL, contains_secret_value INTEGER NOT NULL,
 injection_suspected INTEGER NOT NULL, classifier_version TEXT NOT NULL,
 explanation TEXT NOT NULL, user_override TEXT, UNIQUE(content_hash,event_ts));
CREATE INDEX idx_mem_ts ON memories(event_ts);
CREATE INDEX idx_mem_sens ON memories(sensitivity);
CREATE INDEX idx_mem_batch ON memories(batch_id);
CREATE TABLE entities(id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('person','project','topic')), name TEXT NOT NULL, UNIQUE(kind,name));
CREATE TABLE memory_entities(memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE, entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE, PRIMARY KEY(memory_id,entity_id));
CREATE TABLE classification_evidence(memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE, rule TEXT NOT NULL, tier TEXT NOT NULL, evidence TEXT NOT NULL);
CREATE TABLE corrections(id INTEGER PRIMARY KEY, memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE, ts INTEGER NOT NULL, old_tier TEXT NOT NULL, new_tier TEXT NOT NULL, reason TEXT NOT NULL);
CREATE VIRTUAL TABLE memory_fts USING fts5(summary,people,projects,topics, tokenize='porter unicode61');
CREATE TRIGGER delete_fts AFTER DELETE ON memories BEGIN DELETE FROM memory_fts WHERE rowid=old.rowid; END;
""",
"raw": """
CREATE TABLE raw_events(id TEXT PRIMARY KEY, batch_id TEXT NOT NULL,
 type TEXT NOT NULL CHECK(type IN ('transcript','note','shell_history','browser_metadata','clipboard')),
 content_enc BLOB NOT NULL, content_hash TEXT NOT NULL, event_ts INTEGER NOT NULL,
 ingested_ts INTEGER NOT NULL, injection_suspected INTEGER NOT NULL, expires_ts INTEGER NOT NULL,
 UNIQUE(content_hash,event_ts));
CREATE INDEX idx_raw_ts ON raw_events(event_ts);
CREATE INDEX idx_raw_batch ON raw_events(batch_id);
CREATE INDEX idx_raw_exp ON raw_events(expires_ts);
""",
"audit": """
CREATE TABLE routing_audit(id INTEGER PRIMARY KEY, ts INTEGER NOT NULL, action TEXT NOT NULL,
 max_tier TEXT NOT NULL, path TEXT NOT NULL CHECK(path IN ('local_ai','cloud_ai','blocked')),
 settings_hash TEXT NOT NULL, reasons TEXT NOT NULL);
CREATE TABLE deletion_log(id INTEGER PRIMARY KEY, ts INTEGER NOT NULL, scope TEXT NOT NULL, rows_deleted INTEGER NOT NULL);
"""}


def connect(path, readonly=False):
    if not path.is_file() or path.is_symlink():
        raise SafeError("Storage file missing or unsafe.", "STORAGE_ERROR")
    db = sqlite3.connect(path.as_uri() + ("?mode=ro" if readonly else "?mode=rw"), uri=True, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA secure_delete=ON")
    if db.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
        db.close()
        raise SafeError("Unsupported database version; use a compatible release.", "SCHEMA_VERSION")
    return db


def initialize(root):
    for name, ddl in SCHEMAS.items():
        path = root / (name + ".db")
        path.touch(exist_ok=False)
        secure(path)
        db = sqlite3.connect(path)
        try:
            # DELETE journals enable SQLite's super-journal atomic commit across
            # attached files. WAL would sacrifice that crash-atomic guarantee.
            db.execute("PRAGMA journal_mode=DELETE")
            db.execute("PRAGMA synchronous=FULL")
            db.executescript(ddl)
            db.execute("PRAGMA user_version=1")
            db.commit()
        finally:
            db.close()


@contextmanager
def transaction(root):
    db = connect(root / "memories.db")
    try:
        for name in ("raw", "audit"):
            path = root / (name + ".db")
            if not path.is_file() or path.is_symlink():
                raise SafeError("Storage file missing or unsafe.", "STORAGE_ERROR")
            db.execute("ATTACH DATABASE ? AS " + name, (str(path),))
            if db.execute("PRAGMA " + name + ".user_version").fetchone()[0] != SCHEMA_VERSION:
                raise SafeError("Unsupported database version.", "SCHEMA_VERSION")
            db.execute("PRAGMA " + name + ".secure_delete=ON")
            db.execute("PRAGMA " + name + ".synchronous=FULL")
        db.execute("BEGIN IMMEDIATE")
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def audit(db, verdict, settings, action, schema="audit."):
    digest = hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()
    db.execute("INSERT INTO " + schema + "routing_audit(ts,action,max_tier,path,settings_hash,reasons) VALUES(?,?,?,?,?,?)",
               (int(time.time()), action, verdict["max_tier"], verdict["path"], digest, json.dumps(verdict["reasons"])))


def audit_verdict(root, verdict, settings, action):
    db = connect(root / "audit.db")
    try:
        with db:
            audit(db, verdict, settings, action, "")
    finally:
        db.close()


def insert(db, event, memory, classification, vault, batch_id, settings):
    now = int(time.time())
    # Dedupe persists after raw TTL expiry; no normalized content in this hash.
    digest = hashlib.sha256(event.content.encode("utf-8")).hexdigest()
    if db.execute("SELECT 1 FROM memories WHERE content_hash=? AND event_ts=?", (digest, event.event_ts)).fetchone():
        return None
    event_id, memory_id = str(uuid.uuid4()), str(uuid.uuid4())
    envelope = json.dumps({"app": event.app, "source": event.source, "content": event.content}, ensure_ascii=False)
    db.execute("INSERT INTO raw.raw_events VALUES(?,?,?,?,?,?,?,?,?)",
               (event_id, batch_id, event.type, vault.encrypt(envelope, event_id), digest, event.event_ts, now,
                int(classification["injection_suspected"]), now + settings["raw_retention_days"] * 86400))
    cur = db.execute("""INSERT INTO memories(id,source_event_id,batch_id,event_ts,created_ts,content_hash,summary,sensitivity,
       confidence,contains_secret_value,injection_suspected,classifier_version,explanation) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
       (memory_id, event_id, batch_id, event.event_ts, now, digest, memory["summary"], memory["sensitivity"], classification["confidence"],
        int(classification["contains_secret_value"]), int(classification["injection_suspected"]), classification["classifier_version"], classification["explanation"]))
    db.execute("INSERT INTO memory_fts(rowid,summary,people,projects,topics) VALUES(?,?,?,?,?)",
               (cur.lastrowid, memory["summary"], " ".join(memory["people"]), " ".join(memory["projects"]), " ".join(memory["topics"])))
    for kind, field in (("person", "people"), ("project", "projects"), ("topic", "topics")):
        for name in memory[field]:
            db.execute("INSERT OR IGNORE INTO entities(kind,name) VALUES(?,?)", (kind, name))
            db.execute("INSERT OR IGNORE INTO memory_entities SELECT ?,id FROM entities WHERE kind=? AND name=?", (memory_id, kind, name))
    db.executemany("INSERT INTO classification_evidence VALUES(?,?,?,?)",
                   [(memory_id, r["rule"], r["tier"], r["evidence"]) for r in classification["matched_rules"]])
    return memory_id


def hydrate(db, row, explain=False):
    obj = {k: row[k] for k in ("id", "source_event_id", "batch_id", "event_ts", "summary", "sensitivity", "confidence", "contains_secret_value", "injection_suspected", "classifier_version", "explanation", "user_override")}
    obj.update(people=[], projects=[], topics=[])
    for entity in db.execute("SELECT kind,name FROM entities JOIN memory_entities ON entity_id=entities.id WHERE memory_id=? ORDER BY name", (row["id"],)):
        obj[{"person": "people", "project": "projects", "topic": "topics"}[entity["kind"]]].append(entity["name"])
    if explain:
        obj["matched_rules"] = [dict(r) for r in db.execute("SELECT rule,tier,evidence FROM classification_evidence WHERE memory_id=?", (row["id"],))]
        obj["corrections"] = [dict(r) for r in db.execute("SELECT ts,old_tier,new_tier,reason FROM corrections WHERE memory_id=?", (row["id"],))]
    return obj

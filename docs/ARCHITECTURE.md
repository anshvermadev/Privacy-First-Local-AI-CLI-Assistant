# Architecture and design note

## Boundaries

```text
JSON file / stdin
       |
validate -> capture filters -> Unicode sanitation -> classify
       |                                      |
       |                    deterministic extraction / optional loopback LLM
       |                                      |
       |                             redact -> classify derived output
       |                                      |
raw.db (encrypted envelope)       memories.db (redacted FTS5 + entities)
       \________________ transaction ______________/
                              |
                    audit.db (verdicts only)

query -> memories.db -> classify query + maximum result tier -> verdict
```

The Python package has no mandatory dependencies. `argparse`, `sqlite3` and pure functions keep the routing/classification logic easy to audit. Optional `cryptography` provides established AES-GCM; `keyring` delegates key custody to the host. There is no custom crypto or database engine.

The optional `ui` extra adds prompt-toolkit for a full-screen terminal workspace. Presentation (`terminal_view.py`) renders literal sanitized/redacted fragments; it never treats stored text as terminal markup. `terminal_ui.py` delegates actions to the same CLI service path and serializes command execution. Background work keeps rendering responsive. Password and confirmation input use in-app dialogs outside command history; passwords are masked and Esc cancels the operation. The workspace overview opens only redacted memory storage and settings metadata. Nothing initializes or imports on startup. History and bounded scrollback are ephemeral; the classic line interface remains available with `--plain` and is used automatically for pipes.

Raw events are untrusted data, never instructions. Sanitization is applied to all event text, including metadata, before classification. Detection examines content, app and source. Structured evidence contains static rule descriptions instead of detected values. Extraction consumes redacted text and returns a fixed schema. Derived values are checked again before storage.

## SQLite schema and transaction choice

`raw.db` holds event IDs, batch IDs, type, original/ingestion/expiry timestamps, a dedupe hash and a content envelope. The envelope contains content, app and source and is encrypted as one authenticated record. There is deliberately no plaintext app/source column.

`memories.db` holds redacted summaries, sensitivity, confidence, flags, rule version and explicit overrides. `entities` and `memory_entities` separate people, projects and topics. `classification_evidence` and `corrections` retain explanations. Normal FTS5 rows share the memory's integer rowid; a deletion trigger removes the indexed row. This avoids the special-delete handling and old SQLite compatibility issues of a contentless FTS table.

`audit.db` records timestamp, action, maximum tier, path, canonical settings hash and static reasons. It never stores queries, raw content, app names, people or correction text.

SQLite fits a single-workstation CLI: no server, reliable indexed queries, FTS5 BM25, bounded resource usage and transactional writes. Foreign keys protect entity/evidence links inside the memory database. Raw-to-memory links are logical cross-file references. Raw TTL expiry deliberately permits memories whose raw source is gone. Content hashes in the memory database keep dedupe working after expiry.

Writes attach all three files under one connection. **Rollback journals, FULL synchronous mode and SQLite's multi-file transaction mechanism** are used instead of WAL, because WAL does not provide atomic commit across attached databases. That is an intentional correction to the blueprint's simultaneous WAL/atomicity suggestions. Reads use separate short-lived read-only memory connections; the search layer has no raw connection. Concurrent writers wait up to ten seconds, then fail with a content-free error.

Schema version 1 is stored in each file's `user_version`. Unsupported versions are rejected without mutation. There is no fictional migration history: future schema changes must add explicit, tested version transitions and backup/rollback procedures before changing this version.

## Search and extraction

Search uses quoted word tokens combined with AND, Porter stemming, BM25 ranking and event-time tie-breaking. User input cannot become arbitrary FTS operators or SQL. Limits are bounded to 1–100 results and queries to 4 KiB. This is keyword search, not semantic retrieval. Interface isolation permits a later search implementation without changing the router.

Names use speech-attribution heuristics plus a user list, projects use aliases/project markers, topics use a small dictionary. Summaries use the first two redacted sentences. These choices are intentionally understandable and approximate; they do not claim general linguistic accuracy.

Optional Ollama extraction has a fixed numeric loopback endpoint, ten-second timeout, 64 KiB response cap, no tools, no redirects and no proxies. Outputs are validated and redacted; any error falls back to deterministic extraction. The local model can only raise the rule classifier's result. The CLI cannot sandbox an independently running Ollama server.

## Routing

Routing is a pure function: maximum input tier, master switch, matching tier flag, requested mode and settings validity determine the verdict. Missing flags are false. Malformed policy or classification never authorizes cloud; `auto` remains local, `cloud_required` blocks. Unknown data defaults personal; failed ingest classification rejects the event entirely before extraction.

Query text is classified independently, so an empty search result cannot launder a credential query into public data. Per-item ingestion decisions and retrieval decisions are audited. Dry runs are read-only, including no audit write.

`gateway.prepare_payload` is a defense-in-depth preview boundary: checks policy again, checks derived fields, redacts credential patterns and known people, and serializes only summary/topics/tier. `gateway.send` always refuses. Actual cloud transport is outside the assignment deliverable; adding a provider must preserve this boundary and add network-level egress tests.

## Key custody and file permissions

A random 256-bit raw key is stored in a system keyring or wrapped with AES-GCM under scrypt (`N=32768`, `r=8`, `p=1`, random 16-byte salt). Encryption uses random 96-bit nonces and event-ID associated data. Key values never enter settings, environment variables, command arguments or diagnostic output. Prompts are interactive. The passphrase mode is portable; keyring availability/security depends on the OS backend.

Directories/files use 0700/0600 on POSIX. On Windows initialization removes inherited permissions and grants the current SID access; doctor checks protected ACLs and allowed principals. Existing nonempty directories are refused. Symlink state files/directories are refused. Same-user races and hostile administrators are not an enforced isolation boundary.

Only raw envelopes are encrypted. FTS, summaries, entities, timestamps and hashes remain readable to the owner. Full-disk encryption is appropriate if those must be protected on stolen media. Do not describe this as full database encryption. A lost raw key does not destroy the memory index; crypto-shredding the whole application would require encrypted memories/index too.

## Lifecycle

`forget` deletes selected rows across files in one transaction, cleans entity orphans, and compacts files. `maintain` expires raw/audit records and optimizes FTS. Retention is explicit maintenance, not a silently installed scheduled task. `wipe` requires confirmation, refuses unexpected files and removes the keyring entry before known state files.

The architecture supports encrypted backup/export in a later release, but this prototype does not create automatic backups that might silently undermine deletion. Ordinary OS backups can retain deleted data and wrapped keys. Stop using the application before manually backing up the dedicated directory. Preserve passphrases separately and use encrypted backup media.

## Prototype scope

No passive watchers, cloud provider transport, vector database, sync, or authentication service is included. The full-screen terminal interface is optional; core commands are cross-platform. `forget --id` removes a memory and its raw event; `forget --all` retains setup while clearing records. `reset` aliases full wipe. The Windows launcher installs UI/crypto dependencies on first use and then starts the existing per-user workspace.

## Schema and deletion reference

| Database/table | Main keys and purpose | Deletion behavior |
|---|---|---|
| raw.raw_events | Event ID, batch ID, event/ingestion/expiry timestamps, content hash, encrypted envelope | Delete by source ID, batch, event-time range, or expiry; raw expiry preserves derived memory. |
| memories.memories | Memory ID, unique source_event_id, batch ID, event timestamp, summary/tier and rule metadata | Targeted, batch, range or all-memory deletion; content hash plus event timestamp supports dedupe. |
| memories.entities / memory_entities | Normalized person/project/topic IDs and memory links | Links cascade when memory is deleted; unreferenced entities are cleaned up. |
| memories.classification_evidence / corrections | Memory foreign key, rule evidence and explicit correction history | Cascade with the associated memory. |
| memories.memory_fts | FTS rowid corresponding to memory rowid | Trigger removes the search entry when the memory is deleted. |
| audit.routing_audit / deletion_log | Timestamp, content-free verdict/policy metadata or deletion count | Explicit maintenance expires old records; full reset removes all audit state. |

Default raw retention is seven days from ingestion; default audit retention is 90 days. `maintain` enforces these limits when invoked; there is no always-running expiry process. Memories persist until explicitly deleted. Range deletion uses original event timestamps, so recent imports of old events are better removed by their batch ID.

`forget --all` retains settings, key metadata and audits. `reset`/`wipe` removes all application state and the key; it refuses unexpected files rather than recursively deleting an arbitrary user directory. SQLite secure-delete and compaction reduce recoverable local records but do not erase snapshots, SSD wear-leveling copies or external backups.

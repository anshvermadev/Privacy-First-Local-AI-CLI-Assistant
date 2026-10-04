# Privacy-First Local AI Memory CLI - Complete Product and Technical Blueprint

Working name: **`local-ai`** (CLI) with an optional background watcher.

Labels used throughout:
- **FACT** - verifiable from the assignment document, or widely documented and stable.
- **ASSUMPTION** - a reasonable guess that should be validated.
- **RECOMMENDATION** - a design decision proposed by this blueprint.

Note on research: competitor details below come from general knowledge up to mid 2026 and were not live-verified for this document. Anything about pricing, ownership, or recent product changes is marked ASSUMPTION and should be re-checked before it goes into a pitch or a README.

---

## 0. How this document improves on the first analysis

| Topic | First analysis | Correction in this blueprint |
|---|---|---|
| Routing of `secret` content | "Blocked when secret content is involved" | Too blunt. Processing secrets **locally** is safe and useful. The correct split is: `local_ai` for local processing, `blocked` only when a cloud path is explicitly required or the data cannot be classified or redacted safely. |
| Classifier | Rules only | Rules first, plus an optional local-model second opinion that can only **raise** a tier, never lower it. |
| Search | FTS5 only | FTS5 for the MVP, with a clean interface so local embeddings can be added later without touching callers. |
| Encryption | Field encryption as an extra | Define a clear threat boundary up front: what encryption does and does not protect against. |
| Scope | Assignment prototype | Separates the **assignment deliverable** (small, auditable) from the **real product path** (daemon, integrations, optional cloud gateway). |

---

## 1. Product Understanding

### 1.1 What are we building?
A local-first command-line agent that:
1. Ingests workstation activity events (clipboard, shell commands, notes, transcripts, browser metadata).
2. Sanitizes them, classifies their privacy sensitivity, and extracts structured long-term memories (people, projects, topics, summary).
3. Stores raw events and memories separately on the user's machine.
4. Lets the user search their own history from the terminal.
5. Decides, for every action, whether processing must stay local, may use a cloud AI, or must be blocked, based on user policy.

### 1.2 Problem it solves
People generate a huge amount of working context (decisions in chat, notes, commands, pages viewed) and forget most of it. Tools that remember it for you tend to send it to the cloud, which is unacceptable for developers handling secrets, company IP, or health and identity data.

### 1.3 Target users
| User | Why they care |
|---|---|
| Individual developers | Want to recall "what did we decide about Stripe keys last week" without pasting logs into a cloud chatbot. |
| Security-conscious engineers and consultants | Handle client data under NDA. |
| Small teams in regulated areas (health, finance) | Cannot legally or contractually ship raw data to third-party AI. |
| Privacy-minded power users | Prefer local control and open tooling. |

### 1.3a Primary persona (ASSUMPTION)
A backend or full-stack developer on macOS or Linux, comfortable with a terminal, using Slack, Obsidian or similar notes, and a browser all day.

### 1.4 Pain points
- Context is scattered across apps and is hard to search.
- Existing "AI memory" products are cloud-first or capture everything indiscriminately (screens, audio).
- Sensitive items (keys, patient data) can end up in an AI prompt by accident.
- No clear way to say "forget the last two hours" and trust it.

### 1.5 Why it matters
Cloud AI adoption is blocked in many teams precisely by data-handling fear. A tool that proves where each byte goes (and refuses when unsure) removes that blocker.

### 1.6 Core value proposition
> "Search everything you worked on, with an enforced guarantee that sensitive data never leaves your machine unless you explicitly allow that tier."

### 1.7 What makes it different (RECOMMENDATION)
1. **Policy-enforced routing as a first-class feature**, not a settings page. Every action returns an auditable verdict.
2. **Text-only, structured memory** instead of screen or audio recording. Much smaller attack surface and storage.
3. **Fail-closed design**: unknown or unclassifiable means no cloud.
4. **Deletion as a designed feature** with time-range forgetting and crypto-shredding path.
5. **Honest threat model**: states what the design does not defend against.

---

## 2. Existing Alternatives and Differentiation

### 2.1 Landscape

| Alternative | Type | Verified/Assumed |
|---|---|---|
| Microsoft Recall | OS-level screenshot memory on Copilot+ PCs | FACT: stores local snapshots, was reworked after privacy criticism to be opt-in with encryption and Windows Hello gating. ASSUMPTION: current details may have changed. |
| Rewind / Limitless | Screen and audio memory app | FACT: originally Mac-focused, recorded screen and audio, mixed local storage with cloud AI features. ASSUMPTION: product direction changed after the company was acquired; verify current status before citing. |
| Screenpipe | Open-source local screen and audio capture with AI search | FACT: open source, local-first, record-everything approach. ASSUMPTION: heavier on CPU and disk than text-only capture. |
| Agent memory frameworks (Mem0, Zep, Letta) | Memory layers for LLM apps | FACT: developer libraries for giving agents memory, often with cloud or self-hosted services. They target app builders, not end-user workstation privacy. |
| Atuin / shell history tools | Shell history search and sync | FACT: focused on shell commands only; Atuin offers optional encrypted sync. No cross-app memory or sensitivity routing. |
| Obsidian / Logseq plus search plugins | Manual notes | FACT: local files, user must write everything. No automatic capture or classification. |
| Cloud chat assistants with memory | General AI assistants | FACT: memory lives in the vendor's cloud. |
| Plain `grep` / `ripgrep` over logs | Conventional approach | FACT: fast and private, but no extraction, no classification, no policy. |

### 2.2 Comparison

| Criterion | Recall / Rewind style | Screenpipe style | Agent memory libs | Shell history tools | **local-ai (proposed)** |
|---|---|---|---|---|---|
| Features | Broad (screen) | Broad (screen, audio) | Memory API | Narrow | Medium (text events, classify, route) |
| UX | GUI | GUI plus API | Code | CLI | CLI |
| Workflow | Passive capture | Passive capture | App integrated | Passive | Explicit ingest plus optional watcher |
| Technology | OCR, vision, embeddings | OCR, STT, DB | LLM plus vector/graph | SQLite | SQLite, rules, optional local LLM |
| Limitations | Large capture surface, trust concerns | Resource heavy | Not privacy-policy oriented | Single source | Smaller capture breadth |
| Scalability | Per device | Per device | Server scale | Per device | Per device, tiny footprint |
| Cost | Subscription or OS bundled (ASSUMPTION) | Free or paid tiers (ASSUMPTION) | Usage based (ASSUMPTION) | Free | Free core |
| Automation | High | High | High | Medium | Medium, opt-in |
| Accuracy | Depends on OCR | Depends on OCR/STT | LLM dependent | Exact | Rules deterministic, extraction approximate |
| Key gap | No per-tier cloud policy | Same | Not end-user privacy | No semantics | Narrower sources initially |

### 2.3 Key gaps this product targets
1. **Per-sensitivity cloud policy with explainable verdicts** - none of the above expose this as a core contract (ASSUMPTION based on public descriptions).
2. **Small, auditable, dependency-light footprint** that security teams can review in a day.
3. **Terminal-native workflow** for developers.

### 2.4 Honest weaknesses
- Less capture breadth than screen recorders.
- Rule-based classification will have false positives and negatives.
- A local-only tool has no cross-device story at first.

---

## 3. Methodology

### 3.1 Pipeline
```
Problem: remember work context without leaking it
  → Input: raw JSON events (untrusted)
  → Processing: validate → sanitize → classify → extract → redact
  → Decision: routing engine (policy + max tier)
  → Output: stored memory, search results, JSON routing verdict
```

### 3.2 Step by step
1. **Validate** - strict schema: `type`, `app`, `source`, `content`, `timestamp` (ISO 8601 UTC). Reject unknown types, oversize content, bad timestamps. Cap content length (RECOMMENDATION: 32 KB per event).
2. **Capture-time filter** - drop events from denylisted apps (password managers, terminals running `ssh-add`, keychain tools), and drop strings matching high-entropy secret patterns only if the user chose `--drop-secrets`. Default is to keep and classify.
3. **Sanitize** - normalize Unicode, strip control characters, detect injection-like phrases ("ignore previous instructions", role markers) and set a `injection_suspected` flag. Content is always treated as data.
4. **Classify** - deterministic rules produce a tier plus evidence. See 3.3.
5. **Extract** - build the structured memory. See 3.4.
6. **Redact** - replace secret values and identifiers in the summary with typed placeholders such as `[REDACTED:API_KEY]`.
7. **Store** - raw event to `raw.db`, memory to `memories.db`, linked by event id.
8. **Search** - FTS5 over sanitized summary, topics, people, projects.
9. **Route** - evaluate settings against the maximum tier of everything involved.

### 3.3 Classification logic
Tier order: `public < personal < confidential < secret`. The result is the **highest** tier any rule matches.

| Tier | Example rules |
|---|---|
| secret | Known key prefixes (`sk_live_`, `AKIA`, `ghp_`, `xox`), PEM headers, `password=`, connection strings with credentials, JWT shape, high-entropy tokens (Shannon entropy threshold plus length) |
| personal | Medical terms, patient/ID patterns, government ID formats, email and phone, "private" conversation markers |
| confidential | "roadmap", "revenue", "Q2", "unreleased", "internal", pricing, customer names from a user-maintained list, source `Internal *` |
| public | None of the above matched and source looks public (docs, reference sites) |

**Default for no match: `personal`, not `public`** (RECOMMENDATION). Unknown content should not be treated as shareable. `public` requires a positive signal such as a public documentation domain, or an explicit user allowlist.

Output contract:
```json
{
  "tier": "secret",
  "confidence": 0.9,
  "explanation": "Mentions a Stripe secret key in a security discussion.",
  "matched_rules": [
    {"rule": "keyword.secret_key_mention", "evidence": "secret key", "tier": "secret"}
  ],
  "contains_secret_value": false,
  "injection_suspected": false
}
```

**Important distinction (RECOMMENDATION):** a message that *talks about* a secret is different from one that *contains* one. The assignment's expected output labels sample 1 `secret`, so follow it, but record `contains_secret_value` so downstream logic and reviewers can see you understand the difference.

Applying this to the three samples:
| Sample | Tier | Reason |
|---|---|---|
| Slack, Stripe secret key discussion | secret (matches spec) | Credential topic, no actual value |
| Obsidian, Q2 roadmap and press releases | confidential | Unreleased plans, even though "public launch" appears in text |
| Chrome, patient summary with ID | personal | Medical context plus identifier |

### 3.4 Extraction
- **MVP, deterministic:** capitalized-name heuristics plus a user-editable people list; project names from a user alias list and title-case noun phrases; topics from a keyword dictionary and frequent noun phrases; summary from the first one or two sentences after redaction.
- **Phase 3, optional local LLM** (Ollama or llama.cpp): receives sanitized text inside delimiters, returns JSON validated against a schema. If validation fails, fall back to the deterministic result.
- The LLM has **no tools, no network, no file access**. Its output is data only.

### 3.5 Routing algorithm
Inputs: `settings.json`, tier set of the data involved, requested mode (`auto` or `cloud_required`).

```
tier_max = max(tier of every item involved)
if classification failed or settings invalid:  → blocked (cloud_required) / local_ai (auto)
if not cloud_ai_enabled:                       → local_ai
flag = settings["send_<tier_max>_data_to_cloud"]   (public has no flag: allowed when cloud enabled)
if flag is true:                               → cloud_ai  (with redaction + allowlisted payload)
else if mode == auto:                          → local_ai
else (cloud_required):                         → blocked
```
Extra safety rule (RECOMMENDATION): even when `send_secret_data_to_cloud` is true, secret values are always replaced with placeholders before serialization, and the verdict carries a warning. A setting should not be able to turn a credential into a network payload.

Output:
```json
{
  "path": "local_ai",
  "max_tier": "confidential",
  "mode": "auto",
  "settings_evaluated": {"cloud_ai_enabled": true, "send_confidential_data_to_cloud": false},
  "reasons": ["max tier is confidential", "send_confidential_data_to_cloud is false", "falling back to local processing"],
  "redactions_required": 0
}
```

### 3.6 Validation methodology
- Golden test set of labeled events (start with the three samples, grow to about 200 synthetic ones).
- Metrics: per-tier precision and recall, with **secret recall** as the priority metric (a missed secret is worse than a false alarm).
- Property tests: routing never returns `cloud_ai` when the matching flag is false; `max` is monotonic.

### 3.7 Feedback loop
- `local-ai reclassify <memory_id> --tier X --reason ...` lets the user correct a result.
- Corrections are stored locally and used to build user-specific allowlists and rule weights. They only ever *raise* default strictness automatically; lowering requires an explicit user confirmation.

### 3.8 Uncertainty, failures, edge cases
| Situation | Behavior |
|---|---|
| Classifier error or timeout | Treat as `secret` for routing (fail closed) |
| Invalid or missing settings keys | Treat as `false` |
| Two rules disagree | Highest tier wins |
| LLM extraction invalid JSON | Fall back to deterministic extraction |
| Very large or binary content | Reject or truncate with a stored note |
| Timestamps in the future or bad format | Reject with a clear error |
| Duplicate events | Dedupe by content hash plus timestamp |
| Mixed-tier search results | Route on the maximum tier |

---

## 4. How to Build It

### Phase 1 - Foundation (about 1 day)
- **Build:** repo layout, config loader, event schema, tier enum, logging with redaction, test harness.
- **Why:** everything else depends on safe primitives.
- **Output:** `local-ai --help` runs; schema validation tests pass on the three sample events.

### Phase 2 - MVP (about 2 days)
- **Build:** `ingest`, rule classifier, deterministic extractor, two SQLite DBs, FTS5 search, routing engine, `route` command, `forget`.
- **Why:** these map directly to the six required capabilities.
- **Output:** the documented command sequence works end to end.

### Phase 3 - Core intelligence (about 2 to 3 days)
- **Build:** optional local LLM extraction, entropy and Luhn detectors, injection detector, redaction engine, reclassify feedback.
- **Why:** improves accuracy while staying local.
- **Output:** measurable improvement on the golden set.

### Phase 4 - Testing (ongoing, about 2 days dedicated)
- **Build:** adversarial fixtures, leak tests (fail if content appears in stdout, stderr or logs), cross-platform CI.
- **Output:** green CI on Linux, macOS, Windows.

### Phase 5 - Deployment
- **Build:** packaging for `pipx`, signed releases, checksum file, versioned DB migrations.
- **Output:** one-line install and upgrade.

### Phase 6 - Scaling
- **Build:** background watcher with batching, retention jobs, DB maintenance (VACUUM, FTS optimize), optional per-day encryption keys.
- **Output:** stable multi-week usage with bounded disk growth.

### Phase 7 - Future improvements
- Local embeddings for semantic search, shell and editor integrations, MCP server so other local agents can query memories under the same routing policy, optional vetted cloud gateway with redacted payloads, encrypted export and import.

---

## 5. Complete Tech Stack

Many items from the generic list do not apply to a local CLI. They are marked **N/A** deliberately rather than invented.

| Layer | Choice | Why | Alternatives considered |
|---|---|---|---|
| Language | **Python 3.11+** | Stdlib has `sqlite3`, `json`, `argparse`, `hashlib`; fast to build and review | Go or Rust (better distribution, slower to build), TypeScript (heavier runtime) |
| CLI framework | `argparse` (stdlib) | Zero dependencies | Typer or Click (nicer UX, extra dependency) |
| Frontend | **N/A** (terminal output, optional `--json`). Optional later: Textual TUI | Scope excludes GUIs | Web dashboard (explicitly out of scope) |
| Backend | In-process library; optional local daemon later | No server needed | FastAPI daemon (later, Unix socket) |
| Database | **SQLite** (two files) | Embedded, transactional, ubiquitous | DuckDB (analytics oriented), LMDB, flat JSONL (no indexing or transactions) |
| Search | **SQLite FTS5**, BM25 ranking | Built in, low CPU, no model | Embeddings plus vector DB (heavy), Whoosh/Tantivy (extra dependency) |
| Vector DB | **Postponed.** Later: `sqlite-vec` | Keeps a single storage engine | Chroma, LanceDB, Qdrant (extra process or footprint) |
| Authentication | **N/A** locally; OS file permissions are the boundary. Optional passphrase unlock | Scope excludes auth providers | OAuth/SAML (excluded) |
| AI/LLM | Rules by default; optional **Ollama** with a small model (for example a 3B to 8B instruct model) | Local, swappable | llama.cpp direct, cloud models (only via policy) |
| AI orchestration | Plain Python functions with schema validation | Simple and testable | LangChain or LlamaIndex (heavy, large attack surface) |
| Encryption | `cryptography` package, AES-256-GCM; scrypt for passphrase KDF | Vetted primitives, no custom crypto | SQLCipher (strong, native build issues), `age` (file level) |
| Key storage | OS keyring via `keyring`; passphrase fallback | Uses platform facilities | Env var secrets (visible to child processes), key file (weakest) |
| Storage (files) | Platform data dir via `platformdirs` or manual XDG, Library, AppData | Correct cross-platform locations | Home dotfiles |
| Caching | In-process LRU only | Dataset is small | Redis (unnecessary) |
| Background jobs | Simple scheduler thread or OS scheduler (cron, launchd, Task Scheduler) | No broker needed | Celery (overkill) |
| Queues | In-memory queue within the watcher | Local single process | RabbitMQ, Kafka (overkill) |
| Analytics | **None by default.** Optional opt-in anonymous counters | Contradicts privacy promise otherwise | PostHog or similar (only if opt-in and self-hosted) |
| Monitoring | Local `doctor` command with health checks | No remote telemetry | Sentry (would need scrubbing, off by default) |
| Logging | `logging` with a redacting filter, content never logged | Required by red flags | Structured loggers (fine, but still redact) |
| Security tooling | `bandit`, `pip-audit`, secret scanning in CI, SBOM | Cheap and effective | Commercial SAST (later) |
| CI/CD | GitHub Actions, matrix over three OSes and Python versions | Free for open source | GitLab CI |
| Hosting | **None** for the core. Releases via GitHub and PyPI | Local-first | Cloud hosting only for the later optional gateway |
| Third-party integrations | Ollama (local), OS keyring | Minimal | Slack/Obsidian connectors via exported files first |

---

## 6. System Architecture

### 6.1 High-level architecture
```text
 EVENT SOURCES (untrusted)
 +-----------+  +-----------+  +-----------+  +-----------+
 | JSON file |  | Shell     |  | Clipboard |  | Notes     |
 |           |  | hook      |  | exporter  |  | exporter  |
 +-----------+  +-----------+  +-----------+  +-----------+
       |              |              |              |
       +--------------+------+-------+--------------+
                             |
                             v
 LOCAL-AI CORE PROCESS
 +----------------------------------------------------------+
 |  1. Validator                                            |
 |  2. Sanitizer + injection flagger                        |
 |  3. Classifier (rules, highest tier wins)                |
 |  4. Extractor  - - - (optional) - - ->  [Local LLM]      |
 |  5. Redactor                                             |
 |                                                          |
 |  Search service              Routing engine              |
 +----------------------------------------------------------+
        |           |            |             |
        v           v            v             v
 LOCAL STORAGE (separate trust zones)
 +-----------+ +--------------+ +-----------+ +-------------+
 | raw.db    | | memories.db  | | audit.db  | | settings    |
 | untrusted | | redacted +   | | verdicts  | | .json       |
 | short TTL | | FTS5 index   | | no content| |             |
 +-----------+ +--------------+ +-----------+ +-------------+
       ^              ^
       |  keys        |  keys
       +------+-------+
              |
        +-------------+
        | OS keyring  |
        +-------------+

 Routing engine --(only if policy allows, redacted payload)-->
                                          [Cloud AI via gateway]
```

### 6.2 Layer breakdown
| Layer | Design |
|---|---|
| Frontend | CLI with human-readable and `--json` output. Exit codes are meaningful (0 ok, 2 invalid input, 3 blocked). |
| Backend | Pure Python package with clear modules: `ingest`, `classify`, `extract`, `redact`, `store`, `search`, `route`, `forget`, `crypto`, `logging_safe`. |
| Database | Three SQLite files with different purposes (see section 7). |
| AI layer | Deterministic first; local LLM optional; cloud only through the routing engine. |
| API layer | CLI is the API. Phase 6 adds a local-only socket API with a per-session token. |
| Auth/authz | OS user identity and file permissions. Optional passphrase gate for decryption. |
| Storage layer | Platform data directory, permissions `0700` directory and `0600` files; Windows ACL restricted to the current user. |
| External services | None required. |
| Data pipelines | Synchronous per-event in MVP; batched queue in watcher mode. |
| Background workers | Retention sweeper (deletes expired raw events), FTS optimizer. |
| Monitoring | `local-ai doctor` checks permissions, key availability, DB integrity, settings validity. |

### 6.3 Data flow
```text
 Raw event JSON
       |
       v
 Schema valid? --- no ---> Reject (log event id only)
       |
      yes
       |
       v
 Sanitize + flag injection -----------> [raw.db]
       |
       v
 Classify with rules
       |
       v
 Extract structured memory
       |
       v
 Redact secret values and IDs
       |
       v
 [memories.db + FTS5 index] <----- FTS5 search <----- User query
       |
       v
 Routing engine (max tier + settings)
       |
       +--> local_ai : local answer or results
       |
       +--> cloud_ai : allowlisted redacted payload --> Cloud API
       |
       +--> blocked  : refusal with reasons
```

### 6.4 Component interaction (query path)
```text
 Step  From          To            Message
 ----  ------------  ------------  ------------------------------
  1    User          CLI           local-ai search "Stripe pricing"
  2    CLI           Search        query
  3    Search        memories.db   FTS5 MATCH
  4    memories.db   Search        top-k memories
  5    Search        Router        tiers of results + settings
  6    Router        CLI           verdict (path + reasons)

 Step 7 depends on the verdict:

   local_ai   CLI --> Local LLM   (optional summarize)
              Local LLM --> CLI   text

   cloud_ai   CLI --> Cloud GW    redacted, allowlisted payload
              Cloud GW --> CLI    response

   blocked    CLI --> User        refusal + reasons

  8    CLI           User          results
```

### 6.5 Deployment architecture
```text
 GitHub Releases + PyPI
 (signed package + checksum)
            |
            |  pipx install
            v
 +------------------------------------------------------+
 | DEVELOPER WORKSTATION                                |
 |                                                      |
 |   local-ai (pipx install)                            |
 |      |                                               |
 |      +-- reads/writes -----> Data dir (0700)         |
 |      |                                               |
 |      +-- gets key from ----> OS keyring              |
 |      |                                               |
 |      +-- localhost only ---> Ollama (optional)       |
 +------------------------------------------------------+
            :
            :  blocked unless policy allows
            v
 [ Cloud AI provider ]
```

---

## 7. Database and Data Model

### 7.1 Design principles
1. **Separate trust zones.** `raw.db` is untrusted input. `memories.db` is high-value, derived, and redacted. `audit.db` holds decisions but never content.
2. **Every row is deletable by time and by batch.**
3. **No secret values in any index.**

### 7.2 Schema (SQLite)

```sql
-- raw.db
CREATE TABLE raw_events (
  id            TEXT PRIMARY KEY,            -- uuid7 (time sortable)
  batch_id      TEXT NOT NULL,               -- ingest run id
  type          TEXT NOT NULL CHECK (type IN ('transcript','note','shell_history','browser_metadata','clipboard')),
  app           TEXT NOT NULL,
  source        TEXT NOT NULL,
  content_enc   BLOB NOT NULL,               -- AES-GCM ciphertext (or plaintext in no-crypto mode)
  content_hash  TEXT NOT NULL,               -- sha256 of normalized content, for dedupe
  event_ts      INTEGER NOT NULL,            -- unix seconds, UTC
  ingested_ts   INTEGER NOT NULL,
  injection_suspected INTEGER NOT NULL DEFAULT 0,
  expires_ts    INTEGER NOT NULL,            -- TTL for raw retention
  UNIQUE (content_hash, event_ts)
);
CREATE INDEX idx_raw_event_ts ON raw_events(event_ts);
CREATE INDEX idx_raw_batch    ON raw_events(batch_id);
CREATE INDEX idx_raw_expires  ON raw_events(expires_ts);

-- memories.db
CREATE TABLE memories (
  id             TEXT PRIMARY KEY,
  source_event_id TEXT NOT NULL,             -- logical link to raw_events.id (no FK across files)
  batch_id       TEXT NOT NULL,
  event_ts       INTEGER NOT NULL,
  created_ts     INTEGER NOT NULL,
  summary        TEXT NOT NULL,              -- redacted
  sensitivity    TEXT NOT NULL CHECK (sensitivity IN ('public','personal','confidential','secret')),
  confidence     REAL NOT NULL,
  contains_secret_value INTEGER NOT NULL DEFAULT 0,
  classifier_version TEXT NOT NULL,
  user_override  TEXT                        -- set by reclassify
);
CREATE INDEX idx_mem_ts   ON memories(event_ts);
CREATE INDEX idx_mem_sens ON memories(sensitivity);
CREATE INDEX idx_mem_batch ON memories(batch_id);

CREATE TABLE entities (
  id    INTEGER PRIMARY KEY,
  kind  TEXT NOT NULL CHECK (kind IN ('person','project','topic')),
  name  TEXT NOT NULL,
  UNIQUE (kind, name)
);
CREATE TABLE memory_entities (
  memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
  entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  PRIMARY KEY (memory_id, entity_id)
);

CREATE VIRTUAL TABLE memory_fts USING fts5(
  summary, people, projects, topics,
  content='', tokenize='porter unicode61'
);
-- rowid of memory_fts maps to a rowid column in memories (add INTEGER rowid alias in implementation)

CREATE TABLE classification_evidence (
  memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
  rule      TEXT NOT NULL,
  tier      TEXT NOT NULL,
  evidence  TEXT NOT NULL                    -- short, never a secret value
);

-- audit.db
CREATE TABLE routing_audit (
  id          INTEGER PRIMARY KEY,
  ts          INTEGER NOT NULL,
  action      TEXT NOT NULL,                 -- search, summarize, extract...
  max_tier    TEXT NOT NULL,
  path        TEXT NOT NULL CHECK (path IN ('local_ai','cloud_ai','blocked')),
  settings_hash TEXT NOT NULL,
  reasons     TEXT NOT NULL                  -- JSON array, no content
);
CREATE TABLE deletion_log (
  id INTEGER PRIMARY KEY, ts INTEGER NOT NULL, scope TEXT NOT NULL, rows_deleted INTEGER NOT NULL
);
```

### 7.3 ER diagram
```text
 raw.db
 +-------------------------+
 | raw_events              |
 |-------------------------|
 | id (PK)                 |
 | batch_id                |
 | type, app, source       |
 | content_enc             |
 | event_ts, expires_ts    |
 +-------------------------+
            | 1
            |  logical link: memories.source_event_id
            |  (no cross-file foreign key)
            | 0..many
            v
 memories.db
 +-------------------------+  1      0..many  +---------------------+
 | memories                |------------------| classification_     |
 |-------------------------|                  | evidence            |
 | id (PK)                 |                  |---------------------|
 | source_event_id         |                  | memory_id (FK)      |
 | summary (redacted)      |                  | rule, tier, evidence|
 | sensitivity             |                  +---------------------+
 | event_ts                |
 +-------------------------+
      | 1             | 1
      | 0..many       | 1
      v               v
 +---------------+  +------------------+
 | memory_       |  | memory_fts       |
 | entities      |  | (FTS5 index)     |
 |---------------|  +------------------+
 | memory_id FK  |
 | entity_id FK  |
 +---------------+
      | many
      |
      | 1
      v
 +---------------+
 | entities      |
 |---------------|
 | id (PK)       |
 | kind, name    |
 +---------------+

 audit.db (standalone, no content)
 +-------------------------+
 | routing_audit           |
 |-------------------------|
 | id, ts, action          |
 | max_tier, path          |
 | settings_hash, reasons  |
 +-------------------------+
```

### 7.4 Why separate files instead of separate tables
- Different retention (raw expires quickly, memories last).
- Different keys possible (raw can use a separate key and be crypto-shredded independently).
- Different file permissions or even different locations.
- A bug in memory search can never accidentally read raw content because it does not have the file open.
- Trade-off: no cross-file foreign keys, so integrity of the logical link is checked by a `doctor` command.

### 7.5 Lifecycle
| Data | Retention default (RECOMMENDATION) | Deletion |
|---|---|---|
| raw_events | 7 days TTL | Sweeper, `forget`, `wipe` |
| memories | Until user deletes, optional 1 year cap | `forget`, `wipe` |
| audit | 90 days, no content | Sweeper |
| settings | Permanent | `wipe` |

### 7.6 Permissions
Directory `0700`, files `0600`. On Windows, set an ACL that removes inherited access and grants only the current user. `doctor` verifies and warns.

### 7.7 Validation
Schema CHECK constraints, strict parsing at ingest, max lengths, and parameterized queries only. FTS queries are escaped (quote user terms) to avoid FTS syntax injection.

---

## 8. Complete User Flow

The product is a CLI, so the flow is terminal-first. A later TUI would reuse the same flow.

### 8.1 Onboarding
```
$ pipx install local-ai
$ local-ai init
  → creates data dir (0700), generates key, stores in OS keyring (or asks for passphrase)
  → writes a conservative settings.json (cloud disabled)
  → prints a short plain-language privacy summary
$ local-ai doctor
```
Principle: **safe by default**. Cloud is off until the user turns it on.

### 8.2 Authentication
No accounts. Identity is the OS user. If the keyring is unavailable, prompt for a passphrase once per session. Never accept a passphrase as a command-line argument (it would land in shell history).

### 8.3 Main workflow
| Step | Command | Result |
|---|---|---|
| Ingest | `local-ai ingest mock_events.json` | Summary line: counts per tier, rejected events, no content shown |
| Preview | `local-ai ingest --dry-run file.json` | Shows what would be stored, redacted |
| Search | `local-ai search "Stripe pricing"` | Ranked results with tier badges and reasons |
| Route check | `local-ai route --query "Stripe pricing"` | JSON verdict |
| Inspect | `local-ai show <id> --explain` | Classification evidence |
| Correct | `local-ai reclassify <id> --tier confidential` | Updates and records feedback |
| Forget | `local-ai forget --last 2h` | Count deleted, confirmation prompt |
| Wipe | `local-ai wipe` | Typed confirmation, deletes everything including key |

### 8.4 Results display
Each result shows summary, tier, date, people and projects, and a one-line reason. `--json` gives machine-readable output.

### 8.5 Feedback
`reclassify` and `local-ai allowlist add <source>` let users tune behavior.

### 8.6 Error states
| Error | Message style |
|---|---|
| Invalid JSON | "Event 3: missing field `timestamp`. Nothing from this event was stored." (no content echoed) |
| Keyring unavailable | Explains fallback to passphrase and how to set it |
| Settings invalid | States which key is invalid, applies the safe default |
| Blocked verdict | Shows which rule blocked and what setting would change it |

### 8.7 Empty states
- No memories: "Nothing stored yet. Try `local-ai ingest --help`."
- No search results: suggests broader terms and shows count of memories searched.

### 8.8 Notifications
Terminal only. Optional one-line notices such as "3 events were skipped by the capture denylist." No desktop notifications in MVP.

### 8.9 Settings and account
`local-ai config show|set`, with a warning whenever a setting weakens privacy. Changing a `send_*` flag to true prints exactly what will become eligible for cloud transfer.

### 8.10 Exit and return
No session. State is on disk. `local-ai status` summarizes counts, last ingest, retention, and key status. Uninstall instructions include `wipe`.

### 8.11 UX principles
1. Safe defaults, explicit consent for anything risky.
2. Never print sensitive content unless the user asked for it.
3. Explain every verdict in plain words.
4. Destructive actions need confirmation, with a `--yes` flag for scripts.
5. Everything has a `--json` option for scripting.

---

## 9. API and Backend Design

### 9.1 Primary interface: CLI contract
| Command | Purpose | Input | Output | Validation | Errors |
|---|---|---|---|---|---|
| `init` | Create data dir, key, default settings | optional `--passphrase-prompt` | status | existing install check | exit 1 if already initialized |
| `ingest <file>` | Process events | JSON array or JSONL | counts per tier and rejects | schema, size, timestamp | exit 2 on invalid input |
| `search <query>` | Find memories | text, `--limit`, `--tier`, `--since` | ranked results plus verdict | query length, FTS escaping | exit 0 with empty list if none |
| `route` | Evaluate routing | `--query` or `--memory-id`, `--mode` | JSON verdict | settings schema | exit 3 if blocked |
| `forget` | Targeted deletion | `--last 2h`, `--since`, `--until`, `--batch`, `--tier` | rows deleted | range parsing | exit 2 on bad range |
| `wipe` | Full deletion | typed confirmation | confirmation | none | exit 1 on cancel |
| `show <id>` | Inspect a memory | id | memory plus evidence | id format | exit 4 if not found |
| `reclassify <id>` | Correct a tier | tier, reason | updated record | tier enum | |
| `doctor` | Health check | none | checklist | none | |

### 9.2 Optional local daemon API (Phase 6, ASSUMPTION it will be needed)
Transport: Unix domain socket (Windows named pipe), not a TCP port. If TCP is unavoidable: bind `127.0.0.1` only, require a per-session bearer token stored with `0600`, and check the `Host` and `Origin` headers to defend against DNS rebinding.

| Method | Path | Purpose | Input | Output | Auth |
|---|---|---|---|---|---|
| POST | `/v1/events` | Ingest events | array of events | accepted, rejected counts | token |
| GET | `/v1/memories/search` | Search | `q`, `limit`, `since` | results plus verdict | token |
| POST | `/v1/route` | Routing verdict | action, memory ids | verdict JSON | token |
| DELETE | `/v1/memories` | Time-range delete | `since`, `until` | count | token |
| GET | `/v1/health` | Health | none | status | token |

Error format: `{"error": {"code": "INVALID_EVENT", "message": "...", "event_index": 3}}` with no content echoed.

### 9.3 Service-to-service communication
- In-process function calls in the MVP.
- Watcher to core: in-memory queue.
- Core to local LLM: HTTP to `localhost` Ollama with a timeout and a strict response schema.
- Core to cloud: only through the router, via a single `gateway.send()` function that is the **only** code path allowed to open outbound network connections. This makes review simple: grep for one function.

### 9.4 Future cloud gateway payload (RECOMMENDATION)
Allowlisted fields only: redacted summary, topics, tier label. No raw content, no app names, no people names unless the user opts in to that field.

---

## 10. Security and Reliability

### 10.1 Honest threat boundary (FACT/RECOMMENDATION)
- Encryption at rest and OS keyrings protect against: stolen disks, backups copied elsewhere, other OS users, casual file browsing.
- They do **not** reliably protect against malware running as the same user, since that process can often ask the keyring for the key or read process memory. Say so plainly in docs.

### 10.2 Controls
| Area | Control |
|---|---|
| Authentication | OS user boundary; optional passphrase unlock |
| Authorization | File permissions; daemon token if enabled |
| Data privacy | Local by default; per-tier cloud flags; redaction before serialization |
| Encryption | AES-256-GCM per field or per file; random nonce per record; key from keyring; passphrase via scrypt (never a short-lived plain hash) |
| Key custody | Keyring first, passphrase fallback, never in env vars or config; key rotation command |
| API security | Socket or localhost with token; no CORS; Host/Origin checks |
| Rate limiting | Cap events per minute in watcher, cap query rate on daemon |
| Input validation | Strict schema, size caps, control character stripping |
| Prompt injection | Delimited untrusted data, injection flagging, no-tool LLM, JSON schema validation, never concatenate stored text into a system prompt |
| Abuse prevention | Denylist apps, entropy filter, `--dry-run`, per-source rate limits |
| Backups | User-initiated `export` produces encrypted archive; raw.db excluded by default |
| Disaster recovery | `PRAGMA integrity_check` in `doctor`, nightly SQLite backup API snapshot to a local backup dir (encrypted), documented key recovery (lost key means lost data, state this clearly) |
| Failure handling | Fail closed on classification or settings errors; atomic transactions; migrations are versioned and reversible |
| Logging | Redacting formatter, event ids and hashes only, never content or CLI args containing content |
| Supply chain | Pinned minimal dependencies, `pip-audit`, signed releases, SBOM |

### 10.3 Threat model

| Threat | Risk / impact | Mitigation |
|---|---|---|
| **Host process or file compromise** | Other users or malware read raw state files and extract secrets or personal data | Directory `0700`, files `0600` (ACLs on Windows). AES-GCM encrypted content fields, key in OS keyring. Short TTL on raw events. Raw and memory in separate files with separate keys. Docs state that same-user malware is outside what encryption can stop. |
| **Contextual prompt injection** | Ingested text tells an LLM to reveal data, change policy, or call tools | Treat all content as data. Delimit and label it. Flag instruction-like patterns. Extractor LLM has no tools or network. Output validated against a schema, anything else discarded. Router decisions never depend on LLM output. Stored text is never placed into system prompts. |
| **Implicit cloud exfiltration** | Sensitive data passes filters or leaves in metadata | Classify and redact **before** serialization. Single outbound `gateway.send()` path. Allowlisted payload fields. Default deny on unknown tiers. Route on the **maximum** tier of all items, including search results and metadata such as app names. Egress audit entry for every cloud call. Tests assert no outbound call occurs for blocked tiers. |
| **Sensitive leakage in diagnostics** | Secrets in stderr, shell history, logs, crash dumps | Redacting log filter. Log ids and hashes only. Exceptions carry no content. Secrets and passphrases never passed as CLI arguments (use prompt, stdin, or file). Disable verbose tracebacks by default. CI test greps all output for planted canary secrets. |
| **Unintentional context capture** | Watcher records password generator output, env keys, secure notes | App and source denylist (password managers, keychain apps). Skip content matching secret or high-entropy patterns, or store only a placeholder. Ignore clipboard items flagged as concealed by the OS where supported. `--dry-run` preview. Pause command `local-ai pause`. Short raw TTL. |

### 10.4 Additional threats worth adding (beyond the assignment)
| Threat | Mitigation |
|---|---|
| Malicious or tampered settings file | File permission check, schema validation, `doctor` warning, safe defaults on parse failure |
| Search result leakage via side channels (timing, counts) | Low priority locally, noted as accepted risk |
| Dependency compromise | Minimal deps, pinning, audit |
| SQL or FTS injection | Parameterized queries, escaped FTS terms |
| Residual data after deletion | `secure_delete`, VACUUM, crypto-shredding, honest SSD note |

---

## 11. Scalability

For a local-first tool, "scale" means two things: data volume per user, and number of users supported (distribution, support, updates).

| Stage | Users | What matters | Bottleneck | Action |
|---|---|---|---|---|
| 10 | Friends and testers | Correctness and trust | Classifier quality | Collect labeled corrections locally, fix rules |
| 1,000 | Early adopters | Install experience, cross-OS bugs | Keyring and permission differences across OSes | CI matrix, `doctor`, good error messages, issue templates |
| 10,000 | Community | Support load, rule maintenance | Maintainer time, false positives | Versioned rule packs, community-contributed test fixtures, plugin interface for sources |
| 100,000+ | Broad adoption or teams | Update safety, enterprise needs | Trust (audits), per-user DB growth, optional cloud gateway load | Signed auto-update channel, third-party security review, org policy files, optional hosted gateway on stateless autoscaled services |

Per-user data growth (ASSUMPTION): a few hundred to a few thousand text events per day gives roughly tens to low hundreds of MB per year. SQLite and FTS5 handle this comfortably. Mitigations if needed: raw TTL, periodic VACUUM and `optimize`, archive old memories to an encrypted file.

Search scaling: FTS5 is fast into the millions of rows. Embeddings only when keyword recall proves insufficient, because they add CPU, RAM, and model download cost.

---

## 12. Cost and Infrastructure

| Stage | Infrastructure | Approx cost (ASSUMPTION) |
|---|---|---|
| MVP | GitHub repo, GitHub Actions (free tier), PyPI | Effectively zero |
| Early users | Same, plus domain and docs site on static hosting | Low (domain fee and optional static hosting) |
| Growth | Code signing certificates, a security audit, optional telemetry server only if opt-in | Moderate, dominated by audit and signing |
| Large scale | Optional hosted gateway (stateless containers, a managed queue, observability), support tooling | Significant only if a hosted tier is added; LLM API usage becomes the main variable cost |

Where costs can grow:
1. **Cloud LLM tokens** if the gateway is hosted. Optimize by sending small redacted summaries and caching.
2. **Security audits and signing** at the growth stage.
3. **Support time** across three operating systems.
4. Local compute is borne by the user. Keep default CPU use low (rules first, LLM optional).

Cost-saving principle: the local-first architecture keeps the marginal cost per user close to zero.

---

## 13. Testing Strategy

| Type | Scope | Tools |
|---|---|---|
| Unit | Classifier rules, redactor, routing matrix, time-range parsing | `pytest` |
| Property-based | Router never returns `cloud_ai` when the flag is false; max-tier monotonic; redaction idempotent | `hypothesis` |
| Integration | ingest to store to search to forget on a temp data dir | `pytest` with tmp paths |
| CLI/API tests | Exit codes, `--json` schema, daemon endpoints if present | `pytest` with subprocess |
| E2E | Fresh install in a clean VM or container on three OSes | GitHub Actions matrix |
| Performance | Ingest 100k events, search latency with 1M rows, memory ceiling | custom benchmark script |
| Security | Canary secrets must never appear in stdout, stderr, logs, or cloud payloads; permission checks; injection corpus; fuzzing the JSON parser; `bandit`, `pip-audit` | CI jobs |
| AI evaluation | Golden dataset with per-tier precision and recall; extraction field accuracy; secret recall is the gating metric; regression runs on every rule change | Scripted eval |
| Deletion tests | After `forget`, rows and FTS entries are gone; after `wipe`, no files remain | integration |
| UAT | 5 to 10 developers use it for two weeks, measure false alarms, search success rate, setup time | Interviews and a short survey |

Acceptance gate for MVP (RECOMMENDATION): secret recall of 100 percent on the planted-secret fixtures, zero canary leaks, three-OS CI green.

---

## 14. MVP Definition

| Priority | Feature | Why it is necessary |
|---|---|---|
| **Must have** | JSON ingest with at least two event types | Required capability 1 |
| | Deterministic classifier with explanation | Required capability 3, core trust feature |
| | Structured memory extraction | Required capability 2 |
| | Two-file SQLite storage (raw and memories) | Required capability 4, separation is a graded green flag |
| | FTS5 search CLI | Required capability 5 |
| | Routing engine with JSON verdict, fail closed | Required capability 6 |
| | `forget --last` and `wipe` | Deletion is a named design requirement |
| | Redacting logger and leak test | Red flag avoidance |
| | README, architecture note, threat model | Required deliverables |
| **Should have** | Field encryption with keyring, passphrase fallback | Strengthens privacy story, depends on a dependency |
| | `doctor`, `--dry-run`, `show --explain` | Usability and trust |
| | Injection flagging | Directly tied to a threat scenario |
| | Audit log of routing verdicts | Demonstrates enforceability |
| **Could have** | Optional local LLM extraction | Better quality, more complexity |
| | `reclassify` feedback loop | Useful, not required to prove the design |
| | Shell history exporter script | Demonstrates real capture without system-level hooks |
| **Later** | Embeddings and semantic search | Heavy, unproven need |
| | Background watcher daemon | Out of scope for the prototype |
| | Cloud gateway | Contradicts the local-first prototype goal until policy is solid |
| | Per-day key crypto-shredding, MCP server, TUI, multi-device sync | Valuable but not needed to validate the idea |

Feature-creep guard: if a feature does not strengthen privacy proof, separation, search, or routing, it waits.

---

## 15. Risks and Failure Scenarios

Likelihood is described qualitatively because no real usage data exists yet.

| Category | Risk | Impact | Likelihood / uncertainty | Mitigation |
|---|---|---|---|---|
| Technical | Rule classifier misses a secret | Secret could be routed wrongly | Medium, rules are never complete | Fail closed, entropy detection, golden tests, local-model second opinion that only raises tiers |
| Technical | False positives flood users with `secret` | Poor usability, users disable protections | Medium | Distinguish "mentions" vs "contains", allowlists, reclassify |
| Technical | SQLite corruption or crash during write | Data loss | Low | WAL mode, transactions, backups, `doctor` |
| Technical | Keyring behaves differently across OSes or headless Linux | Cannot decrypt | Medium on Linux servers | Passphrase fallback, clear errors |
| Product | Users want screen and audio capture and see text-only as weak | Low adoption | Uncertain | Position as privacy-first, add sources via exporters |
| Product | Output quality of rule extraction feels poor | Low perceived value | Medium | Optional local LLM, better dictionaries |
| Business | Large vendors bundle similar features | Differentiation erodes | Uncertain | Focus on verifiable policy enforcement and open code |
| UX | Terminal-only limits audience | Smaller market | Known | Later TUI, editor and shell integrations |
| Security | Same-user malware reads data | Full data exposure | Medium, inherent to local tools | Honest docs, short TTL, minimal retention, optional passphrase |
| Security | Prompt injection through stored text | Policy bypass or leakage | Medium if LLM used | Isolation, no tools, schema validation, router independent of LLM |
| Security | Secure deletion not guaranteed on SSD | Residual data | Certain at hardware level | Crypto-shredding, honest documentation |
| Scalability | DB growth over years | Slower search, disk use | Low to medium | TTL, VACUUM, archive |
| Adoption | Trust barrier for a new tool that reads all your context | Slow uptake | High at first | Open source, small codebase, audits, `--dry-run`, no network by default |
| Legal | Capturing third-party data (Slack messages) raises consent questions | Compliance exposure | Uncertain, depends on jurisdiction | User-controlled capture, clear docs, retention limits (consult a lawyer for real deployments) |

---

## 16. Future Roadmap

| Stage | Focus | What changes and why |
|---|---|---|
| **MVP** (about 1 week) | Prove the pipeline | CLI, two DBs, rules, FTS5, routing, forget, docs. Goal: a reviewer can audit the whole privacy story in an hour. |
| **V1** (1 to 2 months) | Real capture and trust | Encryption with keyring, shell and notes exporters, watcher with denylist, local LLM extraction, `reclassify`, signed releases. Goal: daily use by early adopters. |
| **V2** (3 to 6 months) | Semantic recall and ecosystem | Local embeddings via `sqlite-vec`, MCP server so local agents query memories under the same policy, TUI, rule packs, org policy files. Goal: better recall and integration. |
| **Scale** (6 to 12 months and beyond) | Teams and optional cloud | Vetted cloud gateway with redacted payloads, third-party security audit, encrypted export and optional sync, enterprise policy and audit export. Goal: broader adoption without breaking the privacy promise. |

---

## 17. Final Product Blueprint

**Product:** `local-ai`, a local-first AI memory CLI with policy-enforced routing.

**Problem:** Work context is scattered and valuable, but existing AI memory tools send data to the cloud or capture too broadly.

**Users:** Developers, security-conscious professionals, and small regulated teams.

**Solution:** Ingest text events, sanitize, classify, extract structured memories, store locally in separate trust zones, search with FTS5, and route every action through a fail-closed policy engine.

**Differentiation:** Verifiable, per-tier cloud policy with explained verdicts; text-only small footprint; designed deletion; honest threat model.

**Methodology:** Validate → sanitize → classify (highest tier wins, unknown means personal) → extract → redact → store → route on maximum tier.

**Features (MVP):** ingest, classifier with explanations, extraction, two SQLite files, FTS5 search, routing verdicts, `forget`, `wipe`, redacted logging.

**Tech stack:** Python 3.11 stdlib core, SQLite plus FTS5, optional `cryptography` and `keyring`, optional Ollama, GitHub Actions, pipx distribution.

**Architecture:** Core library with isolated modules; `raw.db` (untrusted, TTL), `memories.db` (redacted, FTS5), `audit.db` (decisions only); single outbound gateway function.

**Database:** Time-indexed rows with batch ids for range deletion; entities table; evidence table; CHECK constraints on tiers.

**APIs:** CLI commands with `--json` and meaningful exit codes; later a Unix-socket daemon API with token auth.

**User flow:** `init` → `ingest` (with `--dry-run`) → `search` → `route` → `reclassify` or `forget` → `wipe`.

**Security:** Fail closed, redact before serialization, field encryption with keyring or passphrase, no content in logs, injection isolation, explicit statement of what encryption cannot stop.

**Testing:** Unit, property, integration, canary-leak tests, golden-set classification metrics with secret recall as the gate, three-OS CI.

**Deployment:** PyPI and GitHub Releases, `pipx install`, signed artifacts and checksums.

**Scaling:** SQLite per user; retention and VACUUM for volume; rule packs and CI matrix for adoption; optional stateless gateway only at large scale.

**Roadmap:** MVP (prove pipeline) → V1 (real capture, encryption) → V2 (semantic search, MCP, TUI) → Scale (optional gateway, audits, team policy).

---

### Appendix A - Example `settings.json` interpretation

| Setting | Meaning | Safe default |
|---|---|---|
| `cloud_ai_enabled` | Master switch for any cloud path | false |
| `send_personal_data_to_cloud` | Allow personal tier in cloud payloads | false |
| `send_confidential_data_to_cloud` | Allow confidential tier | false |
| `send_secret_data_to_cloud` | Allow secret tier (values still redacted) | false |
| (no `public` flag) | ASSUMPTION: public follows `cloud_ai_enabled` only | n/a |

### Appendix B - Suggested repository layout
```
local-ai/
  README.md
  docs/ARCHITECTURE.md
  docs/THREAT_MODEL.md
  src/local_ai/
    cli.py  ingest.py  classify.py  extract.py  redact.py
    store.py  search.py  route.py  forget.py  crypto.py  logging_safe.py
  tests/
    fixtures/mock_events.json  fixtures/adversarial.json
    test_classify.py  test_route.py  test_leaks.py  test_forget.py
  settings.example.json
  pyproject.toml
```

### Appendix C - Open questions to validate
1. Should "mentions a secret" and "contains a secret" both route as `secret`? (Assignment implies yes for the sample; consider a sub-label.)
2. Is `public` governed only by `cloud_ai_enabled`? (Assumed yes.)
3. What raw event TTL do real users accept? (7 days assumed.)
4. How often do users want automatic capture versus manual ingest? (Unknown until user testing.)

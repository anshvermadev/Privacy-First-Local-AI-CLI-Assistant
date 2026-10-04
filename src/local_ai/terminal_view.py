"""Presentation only: safe text fragments and a read-only workspace overview."""
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import textwrap

from . import __version__
from .config import load_settings
from .models import sanitize
from .permissions import MARKER, check_state
from .redact import redact
from .store import connect


def safe(value):
    return redact(sanitize(str(value)))[0]


@dataclass
class Workspace:
    initialized: bool = False
    count: int = 0
    encryption: str = "not set up"
    cloud: bool = False
    settings_valid: bool = True
    healthy: bool = True


def workspace(root):
    info = Workspace(initialized=(root / MARKER).is_file())
    if not info.initialized:
        return info
    try:
        check_state(root)
        settings, info.settings_valid = load_settings(root / "settings.json")
        info.cloud = settings["cloud_ai_enabled"]
        obj = json.loads((root / "crypto.json").read_text(encoding="utf-8"))
        info.encryption = {"none": "raw plaintext", "passphrase": "raw encrypted", "keyring": "raw encrypted"}.get(obj.get("mode"), "unknown")
        db = connect(root / "memories.db", readonly=True)
        try:
            info.count = db.execute("SELECT count(*) FROM memories").fetchone()[0]
        finally:
            db.close()
    except Exception:
        info.healthy = False
    return info


def line(text="", style="text"):
    return [("class:" + style, safe(text))]


def wrapped(text, width, style="text", indent="  "):
    return [line(indent + part, style) for part in textwrap.wrap(safe(text), width=max(12, width - len(indent)), replace_whitespace=True) or [""]]


def welcome(info, width):
    rows = [line()]
    if width >= 68:
        rows += [line("  L O C A L  /  A I", "brand"), line("  Your context. Your machine.", "title")]
    else:
        rows += [line("  LOCAL / AI", "brand"), line("  Your context. Your machine.", "title")]
    rows += [line(), *wrapped("A quiet place to remember your work. Search your notes, decisions and conversations without sending them away.", width, "muted"), line()]
    if not info.initialized:
        rows += [line("  START HERE", "accent"), line(),
                 *wrapped("Your workspace needs a one-time setup. Choose encrypted storage for private data:", width),
                 line("  /init --encryption passphrase", "command"), line(),
                 *wrapped("Just exploring? Use the synthetic sample walkthrough:", width, "muted"),
                 line("  /init --no-encryption", "command"),
                 line("  /sample", "command"),
                 *wrapped("The demo option stores raw data as plaintext. Nothing is captured automatically.", width, "muted")]
    elif not info.healthy:
        rows += [line("  WORKSPACE NEEDS ATTENTION", "warning"), *wrapped("Run /doctor to check the storage files before continuing.", width)]
    elif not info.count:
        rows += [line("  MAKE YOUR FIRST MEMORY", "accent"), line(),
                 line("  /remember Your note goes here", "command"),
                 *wrapped("Save something you want to recall later. Then type a few keywords to find it.", width, "muted"), line(),
                 line("  /sample", "command"), *wrapped("Import three synthetic examples: an engineering discussion, a roadmap note and a patient summary.", width, "muted"), line(),
                 line('  /ingest "path/to/events.json"', "command"), *wrapped("Or import your own event file. Preview it first with --dry-run.", width, "muted")]
    else:
        rows += [line("  PICK UP WHERE YOU LEFT OFF", "accent"), line(),
                 line(f"  {info.count} memories, ready to search.", "title"),
                 *wrapped("Type a few keywords below, or use /recent to browse your latest memories.", width, "muted"), line(),
                 line("  Try with the sample data", "muted"), line("  Stripe pricing    ·    marketing roadmap    ·    patient", "command")]
    rows += [line(), line("  /help  commands     /recent  memories     /status  privacy", "muted"), line()]
    return rows


def help_rows(width):
    rows = [line("  YOUR WORKSPACE, FROM THE KEYBOARD", "accent"), line()]
    commands = [
        ("Search words", "Find memories; try Stripe pricing"),
        ("/recent", "Browse the newest memories"), ("/show ID --explain", "Open a memory and its privacy evidence"),
        ("/remember TEXT", "Save a new note directly; quotes are optional"),
        ("/sample", "Import the bundled synthetic examples"), ("/ingest FILE", "Import JSON events; --dry-run previews"),
        ("/init --encryption passphrase", "Set up encrypted raw storage"),
        ("/route --query \"words\"", "Explain a policy decision"),
        ("/status", "Workspace and privacy overview"), ("/doctor", "Check storage, settings and permissions"),
        ("/theme", "Switch between dark and light"), ("/clear", "Clear this view, keeping saved memories"),
        ("/forget --id ID", "Delete one memory and its raw event"),
        ("/forget --all", "Delete all memories, retaining setup"),
        ("/reset", "Hard reset: delete all state and encryption key"),
        ("/forget --last 2h", "Delete a time range with confirmation"),
        ("/exit", "Close the session")]
    for command, description in commands:
        rows += [line("  " + command, "command"), *wrapped(description, width, "muted", "    ")]
    rows += [line(), *wrapped("Tab completes slash commands. Up/Down recalls session inputs. Page Up/Down scrolls results. F1 opens help. Esc clears input. Ctrl+D exits. History stays in memory only.", width, "muted"), line()]
    return rows


def status_rows(info, width):
    rows = [line("  PRIVACY AT A GLANCE", "accent"), line()]
    for label, value in [("Workspace", "ready" if info.initialized else "not initialized"),
                         ("Memories", str(info.count)), ("Raw storage", info.encryption),
                         ("Memory index", "redacted plaintext"),
                         ("Cloud policy", "invalid; denied" if not info.settings_valid else "enabled by settings" if info.cloud else "disabled"),
                         ("Cloud transport", "unavailable; nothing is sent"),
                         ("Session history", "memory only; cleared on exit")]:
        rows += wrapped(f"{label}: {value}", width)
    return rows + [line()]


def result_rows(output, width):
    """Never parse markup from stored text. Every fragment is literal text."""
    rows = []
    memories = output.get("results")
    if "memory" in output:
        memories = [output["memory"]]
    if memories is not None:
        rows += [line(f"  {len(memories)} {'MEMORY' if len(memories) == 1 else 'MEMORIES'} FOUND", "accent"), line()]
        if not memories:
            rows += [*wrapped("No matching memories yet.", width, "title"), *wrapped("Try fewer keywords, /recent to browse, or /sample to load the examples.", width, "muted")]
        for index, memory in enumerate(memories, 1):
            tier = memory["sensitivity"]
            stamp = datetime.fromtimestamp(memory["event_ts"], timezone.utc).strftime("%d %b %Y")
            rows.append([("class:muted", f"  {index:02d}  "), ("class:tier." + tier, f" {tier.upper()} "), ("class:muted", f"  {stamp}")])
            rows += wrapped(memory["summary"], width, "text", "      ")
            parts = memory["people"] + memory["projects"] + memory["topics"]
            if parts:
                rows += wrapped(" · ".join(dict.fromkeys(parts)), width, "muted", "      ")
            rows += wrapped(f"/show {index} --explain", width, "subtle", "      ")
            if "matched_rules" in memory:
                rows += wrapped(memory["explanation"], width, "muted", "      ")
                for rule in memory["matched_rules"]:
                    rows += wrapped(rule["rule"] + ": " + rule["evidence"], width, "muted", "      ")
                for correction in memory.get("corrections", []):
                    rows += wrapped("Correction: " + correction["old_tier"] + " → " + correction["new_tier"] + ". " + correction["reason"], width, "muted", "      ")
            rows += [line()]
    elif "accepted" in output:
        note = output.get("operation") == "remember"
        title = "  PREVIEW READY" if output.get("dry_run") else ("  NOTE SAVED" if output["accepted"] else "  NOTE ALREADY SAVED" if output["duplicates"] else "  NOTE NOT SAVED") if note else "  IMPORT COMPLETE"
        rows += [line(title, "warning" if output["rejected"] else "success"), line(),
                 *wrapped(f"{output['accepted']} accepted  ·  {output['duplicates']} duplicates  ·  {output['dropped']} filtered  ·  {output['rejected']} rejected", width)]
        if output["tiers"]:
            rows += wrapped("  ·  ".join(f"{count} {tier}" for tier, count in output["tiers"].items()), width, "muted")
        rows += wrapped("Batch: " + output["batch_id"], width, "subtle")
        for error in output["errors"]:
            rows += wrapped(f"Event {error['event_index']}: {error['message']}", width, "warning")
        for memory in output.get("preview", []):
            rows += wrapped("[" + memory["sensitivity"] + "] " + memory["summary"], width)
        for memory in output.get("saved_memories", []):
            rows += [line(), *wrapped(memory["summary"], width)]
            if memory["people"]:
                rows += wrapped("People: " + ", ".join(memory["people"]), width, "muted")
            if memory["projects"]:
                rows += wrapped("Projects: " + ", ".join(memory["projects"]), width, "muted")
            rows += wrapped(memory["explanation"], width, "muted")
        rows += [line(), *wrapped("Type keywords from your note to find it, or /recent to browse." if note else "Try Stripe pricing to search the sample discussion, or /recent to browse.", width, "muted")]
    elif "initialized" in output:
        rows += [line("  WORKSPACE READY", "success"), line(), *wrapped(output["note"], width), line(),
                 line("  Next: /remember Your first note", "command")]
    elif "checks" in output:
        rows += [line("  ALL CHECKS PASSED" if output["ok"] else "  SOME CHECKS NEED ATTENTION", "success" if output["ok"] else "warning"), line()]
        for check in output["checks"]:
            rows += wrapped(("PASS  " if check["ok"] else "CHECK ") + check["check"].replace("_", " "), width, "success" if check["ok"] else "warning")
    elif "path" not in output:
        rows += [line("  DONE", "success")]
        for key, value in output.items():
            rows += wrapped(key.replace("_", " ").capitalize() + ": " + (", ".join(map(str, value)) if isinstance(value, list) else str(value)), width)
    verdict = output.get("verdict", output if "path" in output else None)
    if verdict:
        text = {"local_ai": "LOCAL PROCESSING", "cloud_ai": "CLOUD ELIGIBLE · NO REQUEST SENT", "blocked": "CLOUD REQUEST BLOCKED"}[verdict["path"]]
        rows += [line(), *wrapped(text + "  /  " + verdict["max_tier"], width, "warning" if verdict["path"] == "blocked" else "success")]
        rows += wrapped(" · ".join(verdict["reasons"]), width, "muted")
    return rows + [line()]

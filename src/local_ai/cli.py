"""Terminal and JSON API. Never print arbitrary exception or parser values."""
import argparse
from datetime import datetime, timezone
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import time

from .interaction import ask, handler
from . import __version__
from .classify import classify
from .config import DEFAULTS, data_dir, load_settings
from .crypto import Vault, write_private
from .doctor import doctor
from .forget import forget, wipe, reclassify, maintain
from .ingest import decode_events, ingest, MAX_INPUT
from .models import SafeError, Tier, duration, utc_timestamp, sanitize
from .permissions import MARKER, secure, check_state
from .route import route
from .search import search, show, recent
from .store import initialize, audit_verdict


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise SafeError("Invalid command or arguments. Use local-ai --help.")


def parser():
    p = Parser(description="Local memory with privacy classification and explainable routing")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--data-dir", type=Path, default=data_dir())
    p.add_argument("--json", action="store_true", help="machine-readable output (also accepted after commands)")
    sub = p.add_subparsers(dest="command", required=True, parser_class=Parser)
    def command(name, help):
        c = sub.add_parser(name, help=help)
        c.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
        c.add_argument("--data-dir", type=Path, default=argparse.SUPPRESS)
        return c
    c = command("init", "initialize a private data directory")
    mode = c.add_mutually_exclusive_group()
    mode.add_argument("--encryption", choices=["auto", "keyring", "passphrase"], default="auto")
    mode.add_argument("--no-encryption", action="store_true", help="explicitly store raw data in plaintext")
    c = command("ingest", "ingest an event JSON object or array")
    c.add_argument("file", help="JSON file or - for stdin")
    c.add_argument("--dry-run", action="store_true")
    c.add_argument("--drop-secrets", action="store_true")
    c = command("remember", "save a typed note through the same private memory pipeline")
    c.add_argument("text", nargs="?", help="note text; omitted to prompt without putting it in shell history")
    c.add_argument("--dry-run", action="store_true")
    for name in ("search", "route"):
        c = command(name, "search memories and evaluate policy" if name == "search" else "evaluate routing without sending data")
        if name == "search":
            c.add_argument("query")
        else:
            scope = c.add_mutually_exclusive_group(required=True)
            scope.add_argument("--query")
            scope.add_argument("--ids", nargs="+")
            scope.add_argument("--tier", choices=[t.name for t in Tier], help="hypothetical policy check")
        c.add_argument("--limit", type=int, default=20)
        c.add_argument("--since")
        c.add_argument("--mode", choices=["auto", "cloud_required"], default="auto")
        if name == "search":
            c.add_argument("--tier", choices=[t.name for t in Tier])
    c = command("show", "show a redacted memory")
    c.add_argument("id")
    c.add_argument("--explain", action="store_true")
    c = command("reclassify", "record an explicit sensitivity correction")
    c.add_argument("id")
    c.add_argument("--tier", choices=[t.name for t in Tier], required=True)
    c.add_argument("--reason", required=True)
    c.add_argument("--confirm-lower", action="store_true")
    c = command("forget", "delete memories and raw events by event time or batch")
    scope = c.add_mutually_exclusive_group(required=True)
    scope.add_argument("--last")
    scope.add_argument("--since")
    scope.add_argument("--batch")
    scope.add_argument("--id", dest="memory_id", help="delete one memory and its raw event")
    scope.add_argument("--all", dest="all_memories", action="store_true", help="delete all memories and raw events, retaining setup")
    c.add_argument("--until")
    c.add_argument("--yes", action="store_true")
    c = command("reset", "hard reset: remove all application state and the key")
    c.add_argument("--yes", action="store_true")
    c = command("wipe", "remove all application state and the key")
    c.add_argument("--yes", action="store_true")
    command("doctor", "check integrity, permissions, settings and key metadata")
    command("maintain", "expire raw/audit records and compact storage")
    c = command("shell", "open the terminal workspace; type searches without repeated commands")
    c.add_argument("--plain", action="store_true", help="use the basic line interface instead of the full-screen UI")
    c = command("recent", "browse the newest redacted memories")
    c.add_argument("--limit", type=int, default=10)
    c = command("allowlist", "manage explicit public sources")
    c.add_argument("action", choices=["list", "add", "remove"])
    c.add_argument("source", nargs="?")
    return p


def init(root, mode):
    if root.is_symlink() or (root.exists() and any(root.iterdir())):
        raise SafeError("Init requires a new or empty dedicated data directory.")
    root.mkdir(parents=True, exist_ok=True)
    secure(root)
    # Only write the completion marker after every initialization step succeeds.
    try:
        Vault.initialize(root, mode)
        write_private(root / "settings.json", deepcopy(DEFAULTS))
        initialize(root)
        marker = root / MARKER
        marker.write_text("local-ai state v1\n", encoding="utf-8")
        secure(marker)
    except BaseException:
        # The directory was empty on entry. Remove only our known partial
        # artifacts, never recursively remove the directory or unknown files.
        from .crypto import remove_key
        if (root / "crypto.json").exists():
            remove_key(root)
        names = {"crypto.json", "settings.json", MARKER}
        names.update(name + suffix for name in ("raw", "memories", "audit") for suffix in (".db", ".db-journal"))
        for path in root.iterdir():
            if path.name in names and path.is_file() and not path.is_symlink():
                path.unlink()
        raise
    return {"initialized": True, "encryption": json.loads((root / "crypto.json").read_text())["mode"],
            "cloud_enabled": False, "note": "Raw content and metadata are encrypted unless explicitly disabled. Redacted memories and FTS index remain plaintext."}


def confirm(message, yes):
    if yes:
        return
    if handler.get() is None and not sys.stdin.isatty():
        raise SafeError("Destructive operation requires --yes or interactive confirmation.", "CONFIRMATION_REQUIRED")
    if ask(message + " Type DELETE to confirm: ") != "DELETE":
        raise SafeError("Operation cancelled.", "CANCELLED")


def run(args):
    root = args.data_dir.expanduser().absolute()
    # Resolve the parent, but check the leaf before resolving so symlinks are rejected.
    if root.is_symlink():
        raise SafeError("State directory cannot be a symbolic link.", "UNSAFE_PATH")
    root = root.resolve()
    if args.command == "init":
        return init(root, "none" if args.no_encryption else args.encryption), 0
    check_state(root)
    settings, valid = load_settings(root / "settings.json")
    if args.command == "remember":
        content = args.text if args.text is not None else ask("Note > ")
        if not content.strip():
            raise SafeError("Enter some note text to remember.")
        event = {"type": "note", "app": "local-ai", "source": "Terminal note", "content": content,
                 "timestamp": datetime.now(timezone.utc).isoformat()}
        vault = None if args.dry_run else Vault.open(root)
        output = ingest(root, [event], settings, valid, vault, dry_run=args.dry_run)
        output["operation"] = "remember"
        output["saved_memories"] = [show(root, memory_id, explain=True) for memory_id in output["memory_ids"]]
        return output, 2 if output["rejected"] else 0
    if args.command == "recent":
        results = recent(root, args.limit)
        verdict = route([m["sensitivity"] for m in results], settings, settings_valid=valid)
        audit_verdict(root, verdict, settings, "recent")
        return {"results": results, "verdict": verdict}, 0
    if args.command == "ingest":
        if args.file == "-":
            data = sys.stdin.buffer.read(MAX_INPUT + 1)
        else:
            with Path(args.file).open("rb") as file:
                data = file.read(MAX_INPUT + 1)
        events = decode_events(data)
        vault = None if args.dry_run else Vault.open(root)
        output = ingest(root, events, settings, valid, vault, dry_run=args.dry_run, drop_secrets=args.drop_secrets)
        return output, 2 if output["rejected"] else 0
    if args.command in ("search", "route"):
        query = getattr(args, "query", None)
        if query is not None:
            results = search(root, query, args.limit, utc_timestamp(args.since) if args.since else None,
                             args.tier if args.command == "search" else None)
            query_class = classify(sanitize(query), settings=settings)
            tiers = [m["sensitivity"] for m in results] + [query_class["tier"]]
        elif args.ids:
            results = [show(root, identifier) for identifier in args.ids]
            tiers = [m["sensitivity"] for m in results]
        else:
            results, tiers = [], [args.tier]
        verdict = route(tiers, settings, args.mode, settings_valid=valid)
        audit_verdict(root, verdict, settings, args.command)
        output = {"results": results, "verdict": verdict} if args.command == "search" else verdict
        return output, 3 if verdict["path"] == "blocked" else 0
    if args.command == "show":
        memory = show(root, args.id, args.explain)
        verdict = route([memory["sensitivity"]], settings, settings_valid=valid)
        audit_verdict(root, verdict, settings, "show")
        return {"memory": memory, "verdict": verdict}, 0
    if args.command == "reclassify":
        return reclassify(root, args.id, args.tier, args.reason, args.confirm_lower), 0
    if args.command == "forget":
        if args.until and not args.since:
            raise SafeError("--until requires --since.")
        since = int(time.time()) - duration(args.last) if args.last else utc_timestamp(args.since) if args.since else None
        until = utc_timestamp(args.until, future_allowed=True) if args.until else None
        confirm("Delete matching raw events and memories?", args.yes)
        return forget(root, since, until, args.batch, args.memory_id, args.all_memories), 0
    if args.command in {"wipe", "reset"}:
        confirm("Permanently remove all local-ai state and its key?", args.yes)
        return wipe(root), 0
    if args.command == "doctor":
        output = doctor(root)
        return output, 0 if output["ok"] else 2
    if args.command == "maintain":
        return maintain(root, settings), 0
    if args.command == "allowlist":
        if not valid:
            raise SafeError("Repair invalid settings before editing the public allowlist.")
        if args.action != "list":
            if not args.source or len(args.source) > 256 or sanitize(args.source) != args.source:
                raise SafeError("Provide a source of at most 256 characters without control characters.")
            if args.action == "add" and args.source not in settings["public_sources"]:
                settings["public_sources"].append(args.source)
            if args.action == "remove" and args.source in settings["public_sources"]:
                settings["public_sources"].remove(args.source)
            write_private(root / "settings.json", settings)
        from .redact import redact
        return {"public_sources": [redact(s)[0] for s in settings["public_sources"]]}, 0
    raise SafeError("Unsupported operation.")


def display(output, json_mode):
    if json_mode or "path" in output or "error" in output:
        print(json.dumps(output, ensure_ascii=True, indent=2))
        return
    if "results" in output:
        if not output["results"]:
            print("No matching memories. Try fewer search words or ingest an event file.")
        for item in output["results"]:
            print(f"[{item['sensitivity']}] {item['id']}\n  {item['summary']}")
            if item["people"] or item["projects"]:
                print("  People: " + ", ".join(item["people"]) + " | Projects: " + ", ".join(item["projects"]))
        print("Route: " + output["verdict"]["path"] + " — " + "; ".join(output["verdict"]["reasons"]))
        return
    print(json.dumps(output, ensure_ascii=True, indent=2))


def main(argv=None):
    if os.name != "nt":
        os.umask(0o077)
    try:
        argv = list(sys.argv[1:] if argv is None else argv)
        args = parser().parse_args(argv or ["shell"])
        if args.command == "shell":
            if args.json:
                raise SafeError("Interactive sessions do not support --json; use individual commands for JSON output.")
            from .shell import interactive
            return interactive(args.data_dir.expanduser().absolute(), plain=args.plain)
        output, code = run(args)
        display(output, args.json)
        return code
    except SafeError as exc:
        print(json.dumps({"error": {"code": exc.code, "message": str(exc)}}), file=sys.stderr)
        return 3 if exc.code == "BLOCKED" else 2
    except (KeyboardInterrupt, EOFError):
        print('{"error":{"code":"CANCELLED","message":"Operation cancelled."}}', file=sys.stderr)
        return 130
    except Exception:
        # Never echo exception strings, paths or arbitrary data from a dependency.
        print('{"error":{"code":"OPERATION_FAILED","message":"Operation failed. Check file access, state integrity and optional dependencies with doctor."}}', file=sys.stderr)
        return 2

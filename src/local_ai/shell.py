"""Persistent terminal session; plain input searches memory, slash commands manage it."""
import shlex
import sys

from .models import SafeError
from .permissions import MARKER

HELP = """Type search words directly, for example: Stripe pricing

/ingest FILE             Import a JSON event file (quote paths containing spaces)
/remember TEXT           Save a note you type directly
/show ID --explain       Inspect a memory
/route --query WORDS     Check routing (quote multiword queries)
/forget --id ID          Delete one memory and its raw event
/forget --all            Delete all memories, keeping setup
/reset                  Hard reset: delete all state and encryption key
/doctor                 Check storage and permissions
/recent                 Browse the newest memories
/init --encryption passphrase   Initialize encrypted storage
/help                   Show this help
/exit                   Leave the session

Other CLI commands also work with a / prefix, including /search,
/reclassify, /forget, /maintain, /allowlist and /wipe.
This session searches stored memories; it is not a generative chatbot.
No terminal history file is saved by local-ai.
"""
COMMANDS = {"init", "ingest", "remember", "search", "route", "show", "reclassify", "forget", "wipe", "reset", "doctor", "maintain", "allowlist", "recent"}


def parse_line(line):
    if len(line.encode("utf-8")) > 8192:
        raise SafeError("Session input exceeds 8 KiB.")
    if not line.startswith("/"):
        return ["search", line]
    if line == "/remember":
        return ["remember"]
    if line.startswith("/remember") and line[len("/remember"):len("/remember") + 1].isspace():
        # Everything after this verb is data, including quotes and flag-like
        # strings. It must never change policy, location or command options.
        text = line[len("/remember"):].lstrip()
        return ["remember", "--", text] if text else ["remember"]
    lexer = shlex.shlex(line[1:], posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    lexer.escape = ""  # Preserve Windows backslashes, including quoted paths.
    try:
        tokens = list(lexer)
    except ValueError:
        raise SafeError("Unclosed quotation mark. Quote paths or phrases as one argument.") from None
    if not tokens or tokens[0] not in COMMANDS:
        raise SafeError("Unknown session command. Type /help.")
    # stdin belongs to this session, not an event stream.
    if tokens[0] == "ingest" and "-" in tokens[1:]:
        raise SafeError("Use a JSON file for ingestion inside a session; stdin is reserved for your input.")
    if any(t == "--data-dir" or t.startswith("--data-dir=") for t in tokens):
        raise SafeError("Exit and start another session to change the data directory.")
    return tokens


def interactive(root, plain=False):
    if not plain and sys.stdin.isatty() and sys.stdout.isatty():
        try:
            from .terminal_ui import TerminalUI
        except ImportError:
            print('Tip: install the full-screen interface with: python -m pip install -e ".[ui]"')
        else:
            return TerminalUI(root).run()
    from .cli import main

    if root.is_symlink():
        raise SafeError("State directory cannot be a symbolic link.", "UNSAFE_PATH")
    print("local-ai | Interactive memory search\nType search words, /help for commands, or /exit to leave.")
    if not (root / MARKER).is_file():
        print("Storage is not initialized. Run /init --encryption passphrase first.\nFor synthetic samples only, use /init --no-encryption.")
    while True:
        try:
            line = input("local-ai> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSession closed.")
            return 0
        if not line:
            continue
        if line in ("/exit", "/quit", "exit", "quit"):
            print("Session closed.")
            return 0
        if line == "/help":
            print(HELP)
            continue
        try:
            tokens = parse_line(line)
        except SafeError as exc:
            print(str(exc), file=sys.stderr)
            continue
        try:
            code = main(["--data-dir", str(root), *tokens])
        except SystemExit:
            # argparse --help should return to the prompt, not kill the session.
            continue
        if tokens[0] in {"wipe", "reset"} and code == 0:
            print("Storage removed. Session closed.")
            return 0

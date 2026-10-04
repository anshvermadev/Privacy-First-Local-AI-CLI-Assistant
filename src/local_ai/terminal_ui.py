"""Optional full-screen terminal workspace. No web server or remote UI assets."""
import asyncio
from importlib import resources
import json
import os

from prompt_toolkit.application import Application
from prompt_toolkit.data_structures import Point
from prompt_toolkit.filters import Condition
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, VSplit, Layout, Window, ConditionalContainer, FloatContainer, Float
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.margins import ScrollbarMargin
from prompt_toolkit.mouse_events import MouseEventType
from prompt_toolkit.styles import DynamicStyle, Style
from prompt_toolkit.widgets import TextArea, Dialog, Label

from .interaction import handler
from . import __version__
from .models import SafeError
from .shell import parse_line
from .terminal_view import workspace, welcome, help_rows, status_rows, result_rows, line, wrapped, safe

SUGGESTIONS = [
    ("/help", "Every command, in one place"),
    ("/recent", "Browse your newest memories"),
    ("/remember", "Save a note directly from this terminal"),
    ("/sample", "Import three synthetic examples"),
    ("/ingest", "Import a JSON file"),
    ("/show", "Inspect a memory by result number or ID"),
    ("/search", "Search with filters and limits"),
    ("/route", "Explain a privacy decision"),
    ("/status", "See storage and privacy settings"),
    ("/doctor", "Check workspace health"),
    ("/init", "Set up a new workspace"),
    ("/theme", "Switch dark / light appearance"),
    ("/clear", "Clear the view, keep your memories"),
    ("/forget", "Delete --id ID, --all, or a time range"),
    ("/reset", "Hard reset: remove all state and encryption key"),
    ("/reclassify", "Correct a memory's sensitivity"),
    ("/maintain", "Apply retention and compact storage"),
    ("/allowlist", "Manage public sources"),
    ("/wipe", "Remove this workspace, with confirmation"),
    ("/exit", "Close the session"),
]


def theme(light=False):
    bg, fg, muted, subtle, accent, border, selected = (
        ("#f4f1ea", "#292722", "#67635b", "#777269", "#a8472f", "#d8d2c7", "#e4ddd0") if light else
        ("#141413", "#eeece5", "#a3a199", "#8b8982", "#df9272", "#35352f", "#eeece5")
    )
    styles = {
        "": f"bg:{bg} {fg}", "text": fg, "title": f"{fg} bold", "brand": f"{accent} bold",
        "accent": accent, "muted": muted, "subtle": subtle, "command": fg,
        "rule": border, "success": "#467b51" if light else "#a6bd91", "warning": "#a04c29" if light else "#e0b17b",
        "input": f"bg:{bg} {fg}", "prompt": f"{accent} bold", "hint": muted,
        "selected": f"bg:{selected} " + (fg if light else "#141413"),
        "tier.secret": "bg:#49302e #f3b3a3", "tier.confidential": "bg:#423c25 #e1ce8c",
        "tier.personal": "bg:#2b3546 #b2cbed", "tier.public": "bg:#293c30 #b8d1af",
    }
    if "NO_COLOR" in os.environ:
        styles = {name: "bold" if name in {"brand", "title", "selected"} else "" for name in styles}
    return Style.from_dict(styles)


class TranscriptControl(FormattedTextControl):
    def __init__(self, owner, *args, **kwargs):
        self.owner = owner
        super().__init__(*args, **kwargs)

    def mouse_handler(self, mouse_event):
        if mouse_event.event_type == MouseEventType.SCROLL_UP:
            self.owner._scroll(-3)
        elif mouse_event.event_type == MouseEventType.SCROLL_DOWN:
            self.owner._scroll(3)
        else:
            return NotImplemented
        return None


class TerminalUI:
    def __init__(self, root, *, input=None, output=None):
        if root.is_symlink():
            raise SafeError("State directory cannot be a symbolic link.", "UNSAFE_PATH")
        self.root = root
        self.info = workspace(root)
        self.busy = False
        self.prompt_future = None
        self.prompt_field = None
        self.light = False
        self.palette_index = 0
        self.scroll_row = 0
        self.blocks = []
        self.last_ids = []
        self.notice = "Search memories · no cloud transport"
        self.history = InMemoryHistory()
        self.input = TextArea(height=1, multiline=False, wrap_lines=False, history=self.history,
                              prompt=[("class:prompt", "you@local-ai > ")], style="class:input",
                              read_only=Condition(lambda: self.busy))
        self.input.buffer.on_text_changed += self._changed
        self.body_control = TranscriptControl(self, self._body, get_cursor_position=lambda: Point(0, self.scroll_row))
        self.body_window = Window(self.body_control, wrap_lines=True, always_hide_cursor=True,
                                  right_margins=[ScrollbarMargin(display_arrows=True)])
        palette = ConditionalContainer(
            Window(FormattedTextControl(self._palette), height=lambda: min(6, len(self.matches())), wrap_lines=False),
            filter=Condition(lambda: bool(self.matches()) and not self.busy))
        content = HSplit([
            Window(FormattedTextControl(self._header), height=2),
            Window(height=1, char="─", style="class:rule"),
            self.body_window,
            palette,
            Window(height=1, char="─", style="class:rule"),
            self.input,
            Window(height=1, char="─", style="class:rule"),
            Window(FormattedTextControl(self._footer), height=1),
        ])
        # Small side margins preserve the reference's uncluttered terminal look.
        layout = FloatContainer(VSplit([Window(width=2), content, Window(width=2)]), floats=[])
        self.container = layout
        self.app = Application(layout=Layout(layout, focused_element=self.input),
                               key_bindings=self._bindings(), full_screen=True,
                               style=DynamicStyle(lambda: theme(self.light)),
                               input=input, output=output, mouse_support=True)

    @property
    def width(self):
        return max(24, self.app.output.get_size().columns - 5)

    def _header(self):
        count = f"{self.info.count} memories" if self.info.initialized else "setup needed"
        left = "* local-ai" if self.width < 65 else "* local-ai  /  memory workspace"
        right = f"{count} · v{__version__}"
        gap = max(2, self.width - len(left) - len(right))
        return [("class:brand", left), ("", " " * gap), ("class:muted", right), ("", "\n")]

    def _footer(self):
        if self.busy:
            return [("class:accent", "◌ Working locally…  "), ("class:muted", "Please wait; your next input stays here.")]
        if self.width < 65:
            return [("class:muted", "Tab commands · PgUp/PgDn scroll · Ctrl+D exit")]
        mode = self.info.encryption if self.info.initialized else "not initialized"
        if self.width < 100:
            return [("class:muted", "Wheel / PgUp/PgDn scroll · Tab commands"),
                    ("class:subtle", "  |  " + mode + " · local only")]
        return [("class:muted", "Wheel / PgUp/PgDn scroll · Ctrl+Home/End · ↑↓ history"),
                ("class:subtle", "   |   " + mode + " · no cloud transport")]

    def rows(self):
        rows = welcome(self.info, self.width)
        for kind, value in self.blocks:
            if kind == "input":
                rows += [line(), line("  > " + value, "accent"), line()]
            elif kind == "result":
                rows += result_rows(value, self.width)
            elif kind == "help":
                rows += help_rows(self.width)
            elif kind == "status":
                rows += status_rows(value, self.width)
            elif kind == "error":
                rows += [line("  SOMETHING NEEDS ATTENTION", "warning"), *wrapped(value, self.width), line()]
            else:
                rows += wrapped(value, self.width, "muted") + [line()]
        return rows

    def _body(self):
        rows = self.rows()
        self.scroll_row = min(max(0, self.scroll_row), max(0, len(rows) - 1))
        return [fragment for row in rows for fragment in [*row, ("", "\n")]]

    def matches(self):
        text = self.input.text
        if not text.startswith("/") or any(c.isspace() for c in text):
            return []
        return [(name, desc) for name, desc in SUGGESTIONS if name.startswith(text)]

    def _palette(self):
        matches = self.matches()
        if not matches:
            return []
        self.palette_index %= len(matches)
        start = max(0, self.palette_index - 5)
        result = []
        for i, (name, desc) in enumerate(matches[start:start + 6], start):
            text = f" {name:<14} {desc}"[:self.width]
            result += [("class:selected" if i == self.palette_index else "class:muted", text.ljust(self.width)), ("", "\n")]
        return result[:-1]

    def _changed(self, buffer):
        self.palette_index = 0

    def _append(self, kind, value):
        start = max(0, len(self.rows()) - 4)
        self.blocks.append((kind, value))
        # Bounded, ephemeral scrollback. Does not change any saved memory.
        self.blocks = self.blocks[-60:]
        self.scroll_row = min(start, max(0, len(self.rows()) - 1))
        self.body_window.vertical_scroll = self.scroll_row
        self.app.invalidate()

    def _scroll(self, amount):
        self.scroll_row = min(max(0, self.body_window.vertical_scroll + amount), max(0, len(self.rows()) - 1))
        self.body_window.vertical_scroll = self.scroll_row
        self.app.invalidate()

    def _bindings(self):
        kb = KeyBindings()
        normal = Condition(lambda: self.prompt_future is None)

        @kb.add("enter", eager=True, filter=normal)
        def submit(event):
            if self.busy:
                return
            text = self.input.text.strip()
            matches = self.matches()
            if matches and text not in {name for name, _ in SUGGESTIONS}:
                text = matches[self.palette_index % len(matches)][0]
            if not text:
                return
            # Never persist history; mask recognized secrets even in recall.
            self.history.append_string(safe(text))
            self.input.buffer.reset()
            self.busy = True
            self.app.create_background_task(self.execute(text))

        @kb.add("tab", eager=True, filter=normal)
        def complete(event):
            matches = self.matches()
            if matches:
                name = matches[self.palette_index % len(matches)][0]
                self.input.text = name + (" " if name in {"/ingest", "/remember", "/show", "/search", "/route", "/init", "/forget", "/reclassify", "/allowlist"} else "")
                self.input.buffer.cursor_position = len(self.input.text)
            elif not self.input.text:
                self.input.text = "/"
                self.input.buffer.cursor_position = 1

        @kb.add("up", eager=True, filter=normal)
        def previous(event):
            if self.matches():
                self.palette_index = (self.palette_index - 1) % len(self.matches())
            else:
                self.input.buffer.history_backward()

        @kb.add("down", eager=True, filter=normal)
        def next_(event):
            if self.matches():
                self.palette_index = (self.palette_index + 1) % len(self.matches())
            else:
                self.input.buffer.history_forward()

        @kb.add("pageup", filter=normal)
        def page_up(event):
            self._scroll(-max(5, self.app.output.get_size().rows // 2))

        @kb.add("pagedown", filter=normal)
        def page_down(event):
            self._scroll(max(5, self.app.output.get_size().rows // 2))

        @kb.add("c-home", filter=normal)
        def oldest(event):
            self._scroll(-len(self.rows()))

        @kb.add("c-end", filter=normal)
        def latest(event):
            self._scroll(len(self.rows()))

        @kb.add("escape", eager=True, filter=normal)
        @kb.add("c-c", filter=normal)
        def cancel_input(event):
            if not self.busy:
                self.input.buffer.reset()

        @kb.add("c-d", filter=normal)
        def exit_(event):
            if not self.busy:
                self.app.exit(result=0)

        @kb.add("c-l", filter=normal)
        def clear(event):
            if not self.busy:
                self.blocks.clear()
                self.scroll_row = 0

        @kb.add("f1", filter=normal)
        def help_(event):
            if not self.busy:
                self._append("help", None)

        return kb

    async def _prompt(self, message, *, password=False):
        future = asyncio.get_running_loop().create_future()
        self.prompt_future = future
        field = TextArea(height=1, multiline=False, password=password)
        self.prompt_field = field
        keys = KeyBindings()

        @keys.add("enter", eager=True)
        def accept(event):
            if not future.done():
                future.set_result(field.text)

        @keys.add("escape", eager=True)
        @keys.add("c-c", eager=True)
        @keys.add("c-d", eager=True)
        def cancel(event):
            if not future.done():
                future.set_exception(SafeError("Operation cancelled. Your workspace is still open.", "CANCELLED"))

        field.control.key_bindings = keys
        dialog = Dialog(title="Unlock / set up encrypted storage" if password else "Input required",
                        body=HSplit([Label(message), field, Label("Enter to continue | Esc to cancel")], key_bindings=keys),
                        with_background=True)
        overlay = Float(content=dialog)
        self.container.floats.append(overlay)
        self.app.layout.focus(field)
        self.app.invalidate()
        try:
            return await future
        finally:
            field.buffer.reset()
            self.container.floats.remove(overlay)
            self.prompt_field = None
            self.prompt_future = None
            self.app.layout.focus(self.input)
            self.app.invalidate()

    async def _run_command(self, args):
        from .cli import run
        loop = asyncio.get_running_loop()

        def prompt(message, *, password=False):
            return asyncio.run_coroutine_threadsafe(
                self._prompt(message, password=password), loop).result()

        token = handler.set(prompt)
        try:
            # to_thread propagates this context only to this command, never to
            # other sessions. All UI changes stay on the application event loop.
            return await asyncio.to_thread(run, args)
        finally:
            handler.reset(token)

    async def execute(self, text):
        """Serialized command execution; database writes cannot be interrupted by another input."""
        from .cli import parser, run

        self._append("input", safe(text))
        try:
            if text in {"/exit", "/quit", "exit", "quit"}:
                self.app.exit(result=0)
                return
            if text == "/clear":
                self.blocks.clear()
                self.scroll_row = 0
                return
            if text == "/theme":
                self.light = not self.light
                self._append("message", "Light theme." if self.light else "Dark theme.")
                return
            if text == "/status":
                self.info = await asyncio.to_thread(workspace, self.root)
                self._append("status", self.info)
                return
            if text == "/help":
                self._append("help", None)
                return
            if text == "/sample":
                if not self.info.initialized:
                    raise SafeError("Set up storage first: /init --encryption passphrase. For a synthetic-only demo, use /init --no-encryption, then /sample.")
                # Resources are bundled in the wheel; no download or user file lookup.
                with resources.as_file(resources.files("local_ai").joinpath("data", "mock_events.json")) as sample:
                    args = parser().parse_args(["--data-dir", str(self.root), "ingest", str(sample)])
                    output, code = await self._run_command(args)
            else:
                tokens = parse_line(text)
                if tokens[0] != "remember" and ("--help" in tokens or "-h" in tokens):
                    self._append("help", None)
                    return
                if tokens[0] == "show" and len(tokens) > 1 and tokens[1].isdigit():
                    number = int(tokens[1])
                    if not 1 <= number <= len(self.last_ids):
                        raise SafeError("Choose a result number from the latest search or /recent listing.")
                    tokens[1] = self.last_ids[number - 1]
                args = parser().parse_args(["--data-dir", str(self.root), *tokens])
                output, code = await self._run_command(args)
            if "results" in output:
                self.last_ids = [m["id"] for m in output["results"]]
            elif "memory" in output:
                self.last_ids = [output["memory"]["id"]]
            elif output.get("saved_memories"):
                self.last_ids = [m["id"] for m in output["saved_memories"]]
            if getattr(args, "json", False):
                self._append("message", json.dumps(output, ensure_ascii=True, indent=2))
            else:
                self._append("result", output)
            if args.command in {"wipe", "reset"} and code == 0:
                self.app.exit(result=0)
                return
            self.info = await asyncio.to_thread(workspace, self.root)
        except SafeError as exc:
            self._append("error", str(exc))
            if exc.code == "NOT_INITIALIZED":
                self._append("message", "Start with /init --encryption passphrase, then /sample or /ingest FILE.")
        except (EOFError, KeyboardInterrupt):
            self._append("message", "Operation cancelled. Your workspace is still open.")
        except Exception:
            self._append("error", "Could not complete that action. Check the file path and run /doctor. No diagnostic content was exposed.")
        finally:
            self.busy = False
            self.app.invalidate()

    def run(self):
        try:
            return self.app.run()
        except EOFError:
            return 0

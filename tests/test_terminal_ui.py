"""Headless keyboard and rendering tests for the optional full-screen UI."""
import asyncio
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from prompt_toolkit.input import create_pipe_input, DummyInput
    from prompt_toolkit.output import DummyOutput
    from prompt_toolkit.data_structures import Size
    from prompt_toolkit.application.current import set_app
    from local_ai.terminal_ui import TerminalUI
except ImportError:
    TerminalUI = None

from local_ai.cli import init
from local_ai.config import DEFAULTS
from local_ai.crypto import Vault
from local_ai.ingest import ingest
from local_ai.terminal_view import workspace, result_rows
import json

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = json.loads((ROOT / "src/local_ai/data/mock_events.json").read_text())


def text_rows(rows):
    return "\n".join("".join(t for _, t in row) for row in rows)


@unittest.skipIf(TerminalUI is None, "Install the ui extra for terminal interaction tests")
class TerminalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="local-ai-ui-")
        self.root = Path(self.temp.name) / "state"
        init(self.root, "none")
        ingest(self.root, FIXTURES, DEFAULTS, True, Vault())

    def tearDown(self):
        self.temp.cleanup()

    async def wait_for(self, predicate):
        for _ in range(200):
            if predicate():
                return
            await asyncio.sleep(0.025)
        self.fail("Terminal did not reach expected state")

    async def test_keyboard_search_completion_theme_and_exit(self):
        with create_pipe_input() as pipe:
            ui = TerminalUI(self.root, input=pipe, output=DummyOutput())
            task = asyncio.create_task(ui.app.run_async())
            try:
                await asyncio.sleep(0.1)
                pipe.send_text("Stripe pricing\r")
                await self.wait_for(lambda: bool(ui.last_ids) and not ui.busy)
                self.assertIn("SECRET", text_rows(ui.rows()))
                self.assertIn("/show 1", text_rows(ui.rows()))
                pipe.send_text("/show 1 --explain\r")
                await self.wait_for(lambda: any(k == "result" and "memory" in v for k, v in ui.blocks) and not ui.busy)
                self.assertIn("keyword.secret_key_mention", text_rows(ui.rows()))
                pipe.send_text("/help\r")
                await self.wait_for(lambda: any(k == "help" for k, _ in ui.blocks) and not ui.busy)
                await asyncio.sleep(0.1)
                screen = ui.app.renderer._last_screen
                rendered = "\n".join("".join(screen.data_buffer[y][x].char for x in range(80)) for y in range(40))
                self.assertIn("YOUR WORKSPACE, FROM THE KEYBOARD", rendered)
                pipe.send_text("/th\t\r")
                await self.wait_for(lambda: ui.light and not ui.busy)
                pipe.send_text("\x1b[A")
                await self.wait_for(lambda: ui.input.text == "/theme")
                pipe.send_text("\x1b")
                await self.wait_for(lambda: not ui.input.text)
                pipe.send_text("/clear\r")
                await self.wait_for(lambda: not ui.blocks and not ui.busy)
                self.assertEqual(workspace(self.root).count, 3)
                pipe.send_text("/")
                await self.wait_for(lambda: bool(ui.matches()))
                pipe.send_text("\x1b[B\r")
                await self.wait_for(lambda: len(ui.last_ids) == 3 and not ui.busy)
                pipe.send_text("\x04")
                self.assertEqual(await asyncio.wait_for(task, 2), 0)
            finally:
                if not task.done():
                    ui.app.exit(result=0)
                    await task

    async def test_error_recovery_recent_and_secret_history(self):
        with create_pipe_input() as pipe:
            ui = TerminalUI(self.root, input=pipe, output=DummyOutput())
            task = asyncio.create_task(ui.app.run_async())
            try:
                await asyncio.sleep(0.1)
                pipe.send_text('/ingest "unterminated\r')
                await self.wait_for(lambda: any(k == "error" for k, _ in ui.blocks) and not ui.busy)
                pipe.send_text("/recent\r")
                await self.wait_for(lambda: len(ui.last_ids) == 3 and not ui.busy)
                canary = "sk_live_TerminalCanary12345"
                pipe.send_text(canary + "\r")
                await self.wait_for(lambda: any(k == "input" and "REDACTED" in v for k, v in ui.blocks) and not ui.busy)
                self.assertNotIn(canary, text_rows(ui.rows()))
                self.assertNotIn(canary, "\n".join(ui.history.get_strings()))
                pipe.send_text("/exit\r")
                self.assertEqual(await asyncio.wait_for(task, 2), 0)
            finally:
                if not task.done():
                    ui.app.exit(result=0)
                    await task

    async def test_status_and_sample_resource(self):
        ui = TerminalUI(self.root, input=DummyInput(), output=DummyOutput())
        await ui.execute("/sample")
        imported = next(v for k, v in ui.blocks if k == "result")
        self.assertEqual(imported["duplicates"], 3)
        await ui.execute("/status")
        self.assertIn("redacted plaintext", text_rows(ui.rows()))

    async def test_typed_note_saves_and_can_be_opened_by_number(self):
        ui = TerminalUI(self.root, input=DummyInput(), output=DummyOutput())
        await ui.execute("/remember Asha said project Atlas roadmap launches in December.")
        self.assertIn("NOTE SAVED", text_rows(ui.rows()))
        self.assertEqual(len(ui.last_ids), 1)
        await ui.execute("/show 1 --explain")
        self.assertIn("context.business", text_rows(ui.rows()))

    async def test_transcript_scroll_keyboard_and_mouse(self):
        with create_pipe_input() as pipe:
            ui = TerminalUI(self.root, input=pipe, output=DummyOutput())
            for number in range(35):
                ui._append("message", f"Earlier output number {number}")
            task = asyncio.create_task(ui.app.run_async())
            try:
                await asyncio.sleep(0.15)
                ui._scroll(len(ui.rows()))
                await asyncio.sleep(0.15)
                initial = ui.body_window.vertical_scroll
                self.assertGreater(initial, 0)
                pipe.send_text("\x1b[5~")  # Page Up
                await self.wait_for(lambda: ui.body_window.vertical_scroll < initial)
                previous = ui.body_window.vertical_scroll
                pipe.send_text("\x1b[<64;10;10M")  # SGR wheel up over transcript
                await self.wait_for(lambda: ui.body_window.vertical_scroll < previous)
                previous = ui.body_window.vertical_scroll
                pipe.send_text("\x1b[<65;10;10M")
                await self.wait_for(lambda: ui.body_window.vertical_scroll > previous)
                pipe.send_text("\x1b[1;5H")  # Ctrl+Home
                await self.wait_for(lambda: ui.body_window.vertical_scroll == 0)
                await asyncio.sleep(0.1)
                screen = ui.app.renderer._last_screen
                rendered = "\n".join("".join(c.char for c in row.values()) for row in screen.data_buffer.values())
                self.assertIn("Earlier output number 0", rendered)
                pipe.send_text("\x1b[1;5F")  # Ctrl+End
                await self.wait_for(lambda: ui.body_window.vertical_scroll > 0)
                await asyncio.sleep(0.1)
                screen = ui.app.renderer._last_screen
                rendered = "\n".join("".join(c.char for c in row.values()) for row in screen.data_buffer.values())
                self.assertIn("Earlier output number 34", rendered)
                self.assertTrue(ui.app.layout.has_focus(ui.input))
                pipe.send_text("/exit\r")
                self.assertEqual(await asyncio.wait_for(task, 2), 0)
            finally:
                if not task.done():
                    ui.app.exit(result=0)
                    await task

    async def test_password_dialog_setup_unlock_and_cancel(self):
        root = Path(self.temp.name) / "encrypted"
        password = "synthetic test passphrase 456"
        with create_pipe_input() as pipe:
            ui = TerminalUI(root, input=pipe, output=DummyOutput())
            task = asyncio.create_task(ui.app.run_async())
            async def answer(value):
                await self.wait_for(lambda: ui.prompt_field is not None)
                field = ui.prompt_field
                pipe.send_text(value + "\r")
                await self.wait_for(lambda: ui.prompt_field is not field)
            try:
                await asyncio.sleep(0.1)
                pipe.send_text("/init --encryption passphrase\r")
                await answer("short")
                await self.wait_for(lambda: not ui.busy)
                self.assertFalse(workspace(root).initialized)
                pipe.send_text("/init --encryption passphrase\r")
                await answer(password)
                await answer("different long passphrase")
                await self.wait_for(lambda: not ui.busy)
                self.assertFalse(workspace(root).initialized)
                pipe.send_text("/init --encryption passphrase\r")
                await answer(password)
                await answer(password)
                await self.wait_for(lambda: ui.info.initialized and not ui.busy)
                pipe.send_text("/remember Atlas roadmap launches in December.\r")
                await self.wait_for(lambda: ui.prompt_field is not None)
                pipe.send_text(password)
                await self.wait_for(lambda: ui.prompt_field.text == password)
                await asyncio.sleep(0.1)
                screen = ui.app.renderer._last_screen
                rendered = "\n".join("".join(c.char for c in row.values()) for row in screen.data_buffer.values())
                self.assertNotIn(password, rendered)
                self.assertIn("***", rendered)
                pipe.send_text("\r")
                await self.wait_for(lambda: not ui.busy)
                self.assertEqual(ui.info.count, 1)
                pipe.send_text("/remember Another note.\r")
                await answer("incorrect password 123")
                await self.wait_for(lambda: not ui.busy)
                self.assertEqual(workspace(root).count, 1)
                pipe.send_text("/remember Another note.\r")
                await self.wait_for(lambda: ui.prompt_field is not None)
                pipe.send_text("\x03")
                await self.wait_for(lambda: not ui.busy)
                self.assertFalse(task.done())
                self.assertIsNone(ui.prompt_field)
                self.assertEqual(workspace(root).count, 1)
                self.assertNotIn(password, text_rows(ui.rows()))
                self.assertNotIn(password, "\n".join(ui.history.get_strings()))
                pipe.send_text("/recent\r")
                await self.wait_for(lambda: any(k == "result" and "results" in v for k, v in ui.blocks) and not ui.busy)
                pipe.send_text("/exit\r")
                self.assertEqual(await asyncio.wait_for(task, 2), 0)
            finally:
                if not task.done():
                    ui.app.exit(result=0)
                    await task

    async def test_narrow_render_and_setup_does_not_write(self):
        class NarrowOutput(DummyOutput):
            def get_size(self):
                return Size(rows=24, columns=50)
        root = Path(self.temp.name) / "uninitialized"
        ui = TerminalUI(root, input=DummyInput(), output=NarrowOutput())
        self.assertIn("one-time setup", text_rows(ui.rows()))
        with set_app(ui.app):
            ui.app.renderer.render(ui.app, ui.app.layout)
        screen = ui.app.renderer._last_screen
        self.assertIsNotNone(screen)
        self.assertLessEqual(screen.height, 24)
        self.assertFalse(root.exists())
        await ui.execute("Stripe pricing")
        self.assertIn("Start with /init", text_rows(ui.rows()))
        self.assertFalse(root.exists())


class PresentationTests(unittest.TestCase):
    def test_untrusted_text_is_literal_sanitized_and_redacted(self):
        text = text_rows(result_rows({"initialized": True, "note": "<b>hi</b>\x1b[31m password=canary-value"}, 70))
        self.assertIn("<b>hi</b>", text)
        self.assertNotIn("\x1b", text)
        self.assertNotIn("canary-value", text)

    def test_public_cloud_verdict_is_not_presented_as_transmission(self):
        text = text_rows(result_rows({"path": "cloud_ai", "max_tier": "public", "reasons": ["No request sent"]}, 80))
        self.assertIn("NO REQUEST SENT", text)

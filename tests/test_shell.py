import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from local_ai.cli import main
from local_ai.models import SafeError
from local_ai.shell import interactive, parse_line


class ShellTests(unittest.TestCase):
    def test_plain_queries_and_windows_paths(self):
        self.assertEqual(parse_line("Stripe pricing"), ["search", "Stripe pricing"])
        self.assertEqual(parse_line('/ingest "D:\\My Notes\\events.json"'), ["ingest", "D:\\My Notes\\events.json"])
        self.assertEqual(parse_line('/route --query "Stripe pricing"'), ["route", "--query", "Stripe pricing"])

    def test_unsafe_or_invalid_session_commands(self):
        for line in ['/ingest -', '/shell', '/unknown', '/ingest "unterminated', '/search text --data-dir other', 'x' * 8193]:
            with self.subTest(line=line[:20]), self.assertRaises(SafeError):
                parse_line(line)

    def test_session_keeps_running_after_error_and_help(self):
        root = Path("missing-session-test-state").absolute()
        out, err = io.StringIO(), io.StringIO()
        with patch("builtins.input", side_effect=["", "/help", '/ingest "unclosed', "Stripe pricing", "patient", "/exit"]), patch("local_ai.cli.main", return_value=0) as execute, contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(interactive(root), 0)
        self.assertEqual(execute.call_count, 2)
        self.assertEqual(execute.call_args_list[0].args[0], ["--data-dir", str(root), "search", "Stripe pricing"])
        self.assertIn("Session closed", out.getvalue())
        self.assertIn("Unclosed quotation", err.getvalue())

    def test_eof_and_ctrl_c_exit_cleanly(self):
        for exception in (EOFError, KeyboardInterrupt):
            with patch("builtins.input", side_effect=exception), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(interactive(Path("missing-session-test-state")), 0)

    def test_json_shell_is_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["shell", "--json"]), 2)

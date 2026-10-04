"""Fresh-user typed notes: real persistence, privacy classification and search."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from local_ai.cli import main, init
from local_ai.shell import parse_line


class RememberTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="local-ai-remember-")
        self.root = Path(self.tmp.name) / "state"
        init(self.root, "none")

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--data-dir", str(self.root), "--json", *args])
        return code, json.loads(out.getvalue() or err.getvalue())

    def test_new_notes_expected_classification_search_and_route(self):
        cases = [
            ("Asha said project Atlas roadmap launches in December.", "confidential", "Atlas roadmap"),
            ("My dentist appointment is Friday at 10 AM.", "personal", "dentist"),
            ("Payment test token sk_live_FAKE1234567890", "secret", "Payment test"),
        ]
        for text, tier, query in cases:
            code, result = self.call(*parse_line("/remember " + text))
            self.assertEqual(code, 0)
            self.assertEqual(result["accepted"], 1)
            self.assertEqual(result["tiers"], {tier: 1})
            self.assertEqual(result["verdict"]["path"], "local_ai")
            self.assertNotIn("sk_live_FAKE1234567890", json.dumps(result))
            code, found = self.call("search", query)
            self.assertEqual(len(found["results"]), 1)
            self.assertEqual(found["results"][0]["sensitivity"], tier)
        _, found = self.call("search", "Atlas roadmap")
        self.assertEqual(found["results"][0]["people"], ["Asha"])
        self.assertEqual(found["results"][0]["projects"], ["Atlas"])
        code, verdict = self.call("route", "--query", "Payment test", "--mode", "cloud_required")
        self.assertEqual(code, 3)
        self.assertEqual(verdict["path"], "blocked")

    def test_quotes_apostrophes_and_flags_are_data(self):
        text = 'Asha\'s note says "hello" --data-dir elsewhere --help'
        tokens = parse_line("/remember " + text)
        self.assertEqual(tokens, ["remember", "--", text])
        code, output = self.call(*tokens)
        self.assertEqual(code, 0)
        self.assertEqual(output["saved_memories"][0]["summary"], text)

    def test_prompted_note_and_preview(self):
        with patch("builtins.input", return_value="A fresh note about gardening."):
            code, output = self.call("remember")
        self.assertEqual(code, 0)
        self.assertEqual(output["accepted"], 1)
        code, output = self.call("remember", "Preview volcano note", "--dry-run")
        self.assertTrue(output["dry_run"])
        self.assertEqual(output["saved_memories"], [])
        _, found = self.call("search", "volcano")
        self.assertEqual(found["results"], [])
        self.assertEqual(self.call("remember", "   ")[0], 2)

    def test_encrypted_note_is_readable_through_redacted_search(self):
        try:
            import cryptography
        except ImportError:
            self.skipTest("Install crypto extra")
        encrypted = Path(self.tmp.name) / "encrypted"
        with patch("local_ai.crypto.passphrase", return_value="a long test passphrase"):
            init(encrypted, "passphrase")
            self.root = encrypted
            code, output = self.call("remember", "Password test password=FAKE-CANARY-ONLY")
        self.assertEqual(code, 0)
        self.assertNotIn(b"FAKE-CANARY-ONLY", (encrypted / "raw.db").read_bytes())
        self.assertNotIn("FAKE-CANARY-ONLY", json.dumps(output))
        _, found = self.call("search", "Password test")
        self.assertEqual(len(found["results"]), 1)

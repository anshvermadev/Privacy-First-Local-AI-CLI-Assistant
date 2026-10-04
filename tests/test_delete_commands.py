"""Deletion scope and confirmation regressions; only temporary state."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from local_ai.cli import init, parser, run
from local_ai.crypto import Vault
from local_ai.config import DEFAULTS
from local_ai.ingest import ingest
from local_ai.models import SafeError
from local_ai.store import connect

class DeletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "state"
        init(self.root, "none")
        events = json.loads((Path(__file__).resolve().parents[1] / "src/local_ai/data/mock_events.json").read_text())
        self.ids = ingest(self.root, events, DEFAULTS, True, Vault())["memory_ids"]

    def tearDown(self):
        self.temp.cleanup()

    def call(self, *args):
        return run(parser().parse_args(["--data-dir", str(self.root), *args]))[0]

    def count(self, database, table):
        db = connect(self.root / (database + ".db"))
        try:
            return db.execute("SELECT count(*) FROM " + table).fetchone()[0]
        finally:
            db.close()

    def test_one_then_all_preserves_setup_and_cleans_indexes(self):
        result = self.call("forget", "--id", self.ids[0], "--yes")
        self.assertEqual(result, {"memories_deleted": 1, "raw_events_deleted": 1})
        self.assertEqual(self.count("memories", "memories"), 2)
        self.assertEqual(self.count("memories", "memory_fts"), 2)
        self.assertEqual(self.count("raw", "raw_events"), 2)
        with self.assertRaises(SafeError):
            self.call("forget", "--id", "missing", "--yes")
        result = self.call("forget", "--all", "--yes")
        self.assertEqual(result["memories_deleted"], 2)
        for table in ("memories", "memory_fts", "entities", "memory_entities", "classification_evidence"):
            self.assertEqual(self.count("memories", table), 0)
        self.assertEqual(self.count("raw", "raw_events"), 0)
        self.assertTrue((self.root / "crypto.json").exists())
        self.assertTrue((self.root / "settings.json").exists())

    def test_reset_confirmation_and_full_removal(self):
        with patch("local_ai.cli.sys.stdin.isatty", return_value=True), patch("local_ai.cli.ask", return_value="cancel"):
            with self.assertRaises(SafeError):
                self.call("reset")
        self.assertEqual(self.count("memories", "memories"), 3)
        with patch("local_ai.cli.sys.stdin.isatty", return_value=False):
            with self.assertRaises(SafeError):
                self.call("forget", "--all")
        self.assertTrue(self.call("reset", "--yes")["wiped"])
        self.assertFalse(self.root.exists())

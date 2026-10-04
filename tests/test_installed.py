"""Verify a built wheel's package without importing this checkout's src tree."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]


class WheelSmokeTests(unittest.TestCase):
    def test_built_wheel(self):
        wheels = list((ROOT / "dist").glob("privacy_first_local_ai-*.whl"))
        if not wheels:
            self.skipTest("Build the wheel to enable distribution smoke verification")
        wheel = max(wheels, key=lambda p: p.stat().st_mtime)
        with zipfile.ZipFile(wheel) as archive:
            self.assertIn("local_ai/terminal_ui.py", archive.namelist())
            self.assertIn("local_ai/data/mock_events.json", archive.namelist())
        # Python can import a pure-Python wheel as a zip. Isolated mode ignores
        # source PYTHONPATH, user site packages and the working directory.
        script = "import sys; sys.path.insert(0, sys.argv.pop(1)); from local_ai.cli import main; raise SystemExit(main())"
        with tempfile.TemporaryDirectory(prefix="local-ai-wheel-") as temporary:
            prefix = [sys.executable, "-I", "-c", script, str(wheel), "--data-dir", str(Path(temporary) / "state"), "--json"]
            def run(*args):
                result = subprocess.run([*prefix, *args], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)
            run("init", "--no-encryption")
            self.assertEqual(run("ingest", str(ROOT / "src/local_ai/data/mock_events.json"))["accepted"], 3)
            self.assertEqual(run("search", "Stripe pricing")["results"][0]["sensitivity"], "secret")
            run("wipe", "--yes")

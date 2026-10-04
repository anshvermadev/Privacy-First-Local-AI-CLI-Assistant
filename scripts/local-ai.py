"""Run the CLI without installing the package."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from local_ai.cli import main

raise SystemExit(main())

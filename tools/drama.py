#!/usr/bin/env python3
"""Run the project CLI without requiring a global Python installation step."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from short_drama.cli import main

if __name__ == "__main__":
    raise SystemExit(main())

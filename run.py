#!/usr/bin/env python3
"""Entry point.

    python run.py                       # offline demo, no API key needed
    python run.py --source youtube      # live YouTube Data API v3
    python run.py --help                # all options
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())

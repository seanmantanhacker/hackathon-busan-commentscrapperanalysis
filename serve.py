#!/usr/bin/env python3
"""Start the dashboard.

    python serve.py                  # http://localhost:3333 (this machine only)
    python serve.py --lan            # also reachable from other devices on the network
    python serve.py --port 8080
    python serve.py --no-browser
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from web.server import DEFAULT_PORT, serve  # noqa: E402


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open a browser tab.")
    parser.add_argument(
        "--lan",
        action="store_true",
        help="Bind 0.0.0.0 so other devices on the network can open the dashboard. "
             "There is no login — anyone who can reach it can start runs and read reports.",
    )
    parser.add_argument("--host", help="Explicit bind address (overrides --lan).")
    args = parser.parse_args()

    host = args.host or ("0.0.0.0" if args.lan else "127.0.0.1")
    # Auto-opening localhost is pointless when the intent is to share the URL.
    serve(args.port, open_browser=not args.no_browser and host == "127.0.0.1", host=host)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

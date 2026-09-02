#!/usr/bin/env python3
"""Convert an existing Markdown report to PDF.

    python to_pdf.py                                  # newest report in data/output
    python to_pdf.py data/output/report_live.md       # a specific report
    python to_pdf.py report_live.md --out pitch.pdf   # custom destination
    python to_pdf.py --all                            # every report in data/output
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.config import OUTPUT_DIR  # noqa: E402
from src.pdf_export import export_pdf, find_browser  # noqa: E402


def newest_report() -> Path | None:
    reports = sorted(
        (p for p in OUTPUT_DIR.glob("report_*.md")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return reports[0] if reports else None


def convert(path: Path, out: Path | None = None) -> bool:
    result = export_pdf(path, out)
    if result["pdf"]:
        size_kb = result["pdf"].stat().st_size / 1024
        print(f"  PDF  -> {result['pdf']}  ({size_kb:.0f} KB)")
        return True
    print(f"  HTML -> {result['html']}")
    print("  PDF  -> not generated (no Edge/Chrome found). Open the HTML and press Ctrl+P.")
    return False


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("report", nargs="?", type=Path, help="Markdown report (default: newest in data/output)")
    parser.add_argument("--out", type=Path, help="Destination PDF path")
    parser.add_argument("--all", action="store_true", help="Convert every report_*.md in data/output")
    args = parser.parse_args(argv)

    browser = find_browser()
    print(f"Renderer: {browser or 'NONE — will emit HTML only'}")
    print("")

    if args.all:
        reports = sorted(OUTPUT_DIR.glob("report_*.md"))
        if not reports:
            print(f"No report_*.md found in {OUTPUT_DIR}", file=sys.stderr)
            return 1
        ok = True
        for report in reports:
            print(report.name)
            ok = convert(report) and ok
        return 0 if ok else 1

    target = args.report or newest_report()
    if not target:
        print(f"No report found in {OUTPUT_DIR}. Run `python run.py` first.", file=sys.stderr)
        return 1
    if not target.exists() and not target.is_absolute():
        candidate = OUTPUT_DIR / target.name
        if candidate.exists():
            target = candidate

    print(target.name)
    return 0 if convert(target, args.out) else 1


if __name__ == "__main__":
    raise SystemExit(main())

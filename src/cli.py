"""Command-line entry point.

    python run.py                                  # offline demo on fixtures
    python run.py --source youtube                 # live YouTube Data API
    python run.py --source youtube --max-queries 3 # cap quota spend
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import OUTPUT_DIR, get_api_key
from .pipeline import Pipeline, PipelineConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run.py",
        description="Zorvex SNS listening — YouTube comment intelligence for HANGOOD stevia tomato.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--source",
        nargs="+",
        choices=("fixtures", "youtube", "reddit", "threads"),
        default=["fixtures"],
        help="One or more sources. fixtures = offline sample (no keys needed); "
             "youtube = Data API v3; reddit = OAuth script app; threads = Meta token. "
             "Sources that lack credentials are skipped with a warning, not fatal.",
    )
    parser.add_argument(
        "--query-sets",
        nargs="+",
        choices=("core", "competitor", "category"),
        default=["core", "competitor", "category"],
        help="Which query pools from config/taxonomy.json to draw from.",
    )
    parser.add_argument(
        "--max-queries",
        type=int,
        default=6,
        help="Max YouTube searches. Each costs 100 of 10,000 daily quota units (default: 6).",
    )
    parser.add_argument("--videos-per-query", type=int, default=5)
    parser.add_argument("--comments-per-video", type=int, default=100)
    parser.add_argument(
        "--threshold",
        type=float,
        default=1.0,
        help="Relevance score cutoff. Lower = wider net, more noise (default: 1.0).",
    )
    parser.add_argument("--min-segment-size", type=int, default=1)
    parser.add_argument(
        "--subreddits", nargs="+",
        help="Restrict Reddit search to these subreddits (default: a curated food/health list).",
    )
    parser.add_argument(
        "--analyzer",
        choices=("rules", "llm"),
        default="rules",
        help="rules = deterministic lexicon baseline; llm = Claude-assisted (needs ANTHROPIC_API_KEY).",
    )
    parser.add_argument("--no-cache", action="store_true", help="Bypass the local API response cache.")
    parser.add_argument(
        "--pdf",
        action="store_true",
        help="Also export the report as PDF (renders via headless Edge/Chrome).",
    )
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--tag", help="Filename tag for the outputs (default: UTC timestamp).")
    parser.add_argument("--quiet", action="store_true")
    return parser


def _force_utf8_stdout() -> None:
    """Windows consoles default to cp1252 and mangle Korean/Indonesian output."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):  # pragma: no cover - older/redirected streams
            pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdout()
    args = build_parser().parse_args(argv)

    if "youtube" in args.source and not get_api_key():
        print(
            "ERROR: --source youtube needs a YOUTUBE_API_KEY.\n"
            "  1. Get one at https://console.cloud.google.com/ (enable 'YouTube Data API v3')\n"
            "  2. Copy .env.example to .env and paste the key in\n"
            "Or run without --source to use the offline fixture set.",
            file=sys.stderr,
        )
        return 2

    config = PipelineConfig(
        sources=args.source,
        query_sets=args.query_sets,
        max_queries=args.max_queries,
        videos_per_query=args.videos_per_query,
        comments_per_video=args.comments_per_video,
        relevance_threshold=args.threshold,
        min_segment_size=args.min_segment_size,
        subreddits=args.subreddits,
        analyzer=args.analyzer,
        use_cache=not args.no_cache,
        output_dir=args.output_dir,
        verbose=not args.quiet,
    )

    try:
        result = Pipeline(config).run(tag=args.tag)
    except Exception as exc:  # noqa: BLE001 - CLI boundary, report cleanly
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1

    paths = result["paths"]
    stats = result["stats"]

    if args.pdf:
        from .pdf_export import export_pdf

        exported = export_pdf(paths["markdown"])
        paths["pdf"] = exported["pdf"]
        paths["html"] = exported["html"]
        if not exported["pdf"] and not args.quiet:
            print(
                "\n  ! No Edge/Chrome found for PDF rendering — wrote HTML instead.\n"
                "    Open it and press Ctrl+P, or set PDF_BROWSER to a Chromium binary.",
                file=sys.stderr,
            )

    if not args.quiet:
        print("")
        print("=" * 62)
        print("  DONE")
        print("=" * 62)
        print(f"  Analyzed          : {stats['analyzed_comments']} relevant comments")
        print(f"  Segments found    : {len(result['profiles'])}")
        print(f"  Qualified leads   : {stats['qualified_leads']} (grade A/B)")
        print(f"  Avg sentiment     : {stats['avg_sentiment']:+.3f}")
        print("")
        print(f"  Report (markdown) : {paths['markdown']}")
        print(f"  Analysis (json)   : {paths['json']}")
        print(f"  Comments (csv)    : {paths['csv']}")
        if paths.get("pdf"):
            print(f"  Report (pdf)      : {paths['pdf']}")
        print(f"  Always-latest     : {paths['latest']}")
        print("")
        print("  Top recommendations:")
        for rec in result["recommendations"][:3]:
            print(f"    {rec.priority}. {rec.segment_name} -> {rec.channel}")
        print("")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""End-to-end orchestration: fetch → filter → analyze → segment → recommend."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from . import report as report_writer
from .analyze import RulesAnalyzer
from .config import (
    OUTPUT_DIR,
    RAW_DIR,
    ensure_dirs,
    get_api_key,
    get_reddit_credentials,
    get_threads_token,
    load_sentiment_lexicon,
    load_taxonomy,
)
from .recommend import build_recommendations, strategic_notes
from .relevance import RelevanceScorer
from .segments import build_segments, overall_stats
from .comment import Comment
from .youtube_client import YouTubeClient, load_fixture_comments


@dataclass
class PipelineConfig:
    sources: Sequence[str] = ("fixtures",)   # fixtures | youtube | reddit | threads
    query_sets: Sequence[str] = ("core", "competitor", "category")
    max_queries: int = 6              # search.list costs 100 quota units each
    videos_per_query: int = 5
    comments_per_video: int = 100
    relevance_threshold: float = 1.0
    min_segment_size: int = 1
    subreddits: Optional[Sequence[str]] = None
    analyzer: str = "rules"           # "rules" | "llm"
    use_cache: bool = True
    region_code: str = "ID"
    relevance_language: str = "id"
    output_dir: Path = OUTPUT_DIR
    save_raw: bool = True
    verbose: bool = True
    # Called as (percent, message) at each stage. Used by the web dashboard to
    # stream progress; None when running from the CLI.
    on_progress: Optional[Callable[[int, str], None]] = None


class Pipeline:
    def __init__(self, config: PipelineConfig) -> None:
        self.config = config
        self.taxonomy = load_taxonomy()
        self.lexicon = load_sentiment_lexicon()
        self.scorer = RelevanceScorer(self.taxonomy, threshold=config.relevance_threshold)
        self.analyzer_warning: Optional[str] = None
        self.analyzer = self._build_analyzer()
        self.client: Optional[YouTubeClient] = None
        ensure_dirs()

    # ------------------------------------------------------------- analyzer

    def _build_analyzer(self):
        if self.config.analyzer == "llm":
            try:
                from .llm_analyze import LLMAnalyzer

                return LLMAnalyzer(self.taxonomy, self.lexicon)
            except Exception as exc:  # noqa: BLE001 - fall back rather than fail the run
                # Surfaced at the top of run() so the dashboard shows it too —
                # a silent downgrade from Claude to rules would be misleading.
                self.analyzer_warning = (
                    f"  ! Claude-assisted analyzer unavailable ({exc}) — using the rules analyzer instead."
                )
        return RulesAnalyzer(self.taxonomy, self.lexicon)

    def _log(self, message: str) -> None:
        if self.config.verbose:
            print(message, flush=True)

    def _emit(self, percent: int, message: str) -> None:
        """Log to console and report progress to any subscriber (the dashboard)."""
        self._log(message)
        if self.config.on_progress:
            try:
                self.config.on_progress(percent, message)
            except Exception:  # noqa: BLE001 - a broken listener must not kill the run
                pass

    # ---------------------------------------------------------------- fetch

    def _select_queries(self) -> List[str]:
        pools = self.taxonomy["search_queries"]
        queries: List[str] = []
        # Interleave across sets so a low max_queries still covers product,
        # competitor, and category rather than five variants of one theme.
        per_set = [list(pools.get(name, [])) for name in self.config.query_sets if name in pools]
        index = 0
        while len(queries) < self.config.max_queries and any(index < len(p) for p in per_set):
            for pool in per_set:
                if index < len(pool) and len(queries) < self.config.max_queries:
                    queries.append(pool[index])
            index += 1
        return queries

    def fetch(self) -> tuple[List[Comment], Dict[str, Any]]:
        """Collect from every configured source and merge into one comment list."""
        all_comments: List[Comment] = []
        meta: Dict[str, Any] = {"videos": 0, "queries": [], "quota": None, "per_source": {}}

        for source in self.config.sources:
            if source == "fixtures":
                comments = load_fixture_comments()
                self._emit(50, f"[1/5] fixtures -> {len(comments)} comments")
                meta["videos"] += len({c.container_id for c in comments})
                meta["per_source"]["fixtures"] = {"comments": len(comments)}
            elif source == "youtube":
                comments, info = self._fetch_youtube()
                meta["videos"] += info.get("videos", 0)
                meta["queries"] += info.get("queries", [])
                meta["quota"] = info.get("quota")
                meta["per_source"]["youtube"] = info
            elif source == "reddit":
                comments, info = self._fetch_reddit()
                meta["per_source"]["reddit"] = info
            elif source == "threads":
                comments, info = self._fetch_threads()
                meta["per_source"]["threads"] = info
            else:
                self._emit(5, f"  ! unknown source {source!r} - skipped")
                continue
            all_comments.extend(comments)

        if self.config.save_raw and all_comments and set(self.config.sources) != {"fixtures"}:
            raw_path = RAW_DIR / f"comments_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.json"
            raw_path.write_text(
                json.dumps([c.to_dict() for c in all_comments], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self._log(f"      raw comments saved -> {raw_path.name}")

        return all_comments, meta

    # ----------------------------------------------------------- per source

    def _fetch_youtube(self) -> tuple[List[Comment], Dict[str, Any]]:
        self.client = YouTubeClient(
            get_api_key(),
            use_cache=self.config.use_cache,
            region_code=self.config.region_code,
            relevance_language=self.config.relevance_language,
        )
        queries = self._select_queries()
        self._emit(5, f"[1/5] YouTube - {len(queries)} queries, {self.config.videos_per_query} videos each.")

        comments: List[Comment] = []
        seen_videos: set[str] = set()
        seen_ids: set[str] = set()

        for index, query in enumerate(queries):
            try:
                videos = self.client.search_videos(query, max_results=self.config.videos_per_query)
            except Exception as exc:  # noqa: BLE001 - one bad query shouldn't kill the run
                self._log(f"  ! youtube search failed for {query!r}: {exc}")
                continue

            self._emit(
                5 + int(40 * (index + 1) / max(1, len(queries))),
                f"  - youtube {query!r} -> {len(videos)} videos",
            )
            for video in videos:
                if video.video_id in seen_videos:
                    continue
                seen_videos.add(video.video_id)
                try:
                    fetched = self.client.fetch_comments(video, max_comments=self.config.comments_per_video)
                except Exception as exc:  # noqa: BLE001
                    self._log(f"    ! comments failed for {video.video_id}: {exc}")
                    continue
                for comment in fetched:
                    if comment.comment_id and comment.comment_id not in seen_ids:
                        seen_ids.add(comment.comment_id)
                        comments.append(comment)

        self._emit(48, f"      youtube: {len(comments)} comments from {len(seen_videos)} videos.")
        return comments, {
            "videos": len(seen_videos),
            "queries": queries,
            "quota": self.client.quota_report(),
            "comments": len(comments),
        }

    def _fetch_reddit(self) -> tuple[List[Comment], Dict[str, Any]]:
        from .reddit_client import DEFAULT_SUBREDDITS, RedditAuthError, RedditClient, collect

        client_id, client_secret = get_reddit_credentials()
        try:
            client = RedditClient(client_id, client_secret, use_cache=self.config.use_cache)
        except RedditAuthError as exc:
            self._emit(52, f"  ! reddit skipped: {exc}")
            return [], {"comments": 0, "skipped": str(exc)}

        queries = self._select_queries()
        self._emit(50, f"[1/5] Reddit - {len(queries)} queries")
        comments, info = collect(
            client,
            queries,
            posts_per_query=self.config.videos_per_query * 2,
            comments_per_post=self.config.comments_per_video,
            subreddits=self.config.subreddits or DEFAULT_SUBREDDITS,
            log=self._log,
        )
        self._emit(53, f"      reddit: {len(comments)} comments from {info.get('posts', 0)} posts.")
        info["comments"] = len(comments)
        return comments, info

    def _fetch_threads(self) -> tuple[List[Comment], Dict[str, Any]]:
        from .threads_client import ThreadsClient, ThreadsUnavailable, collect

        try:
            client = ThreadsClient(get_threads_token())
        except ThreadsUnavailable as exc:
            self._emit(54, f"  ! threads skipped: {exc}")
            return [], {"comments": 0, "skipped": str(exc)}

        queries = self._select_queries()
        self._emit(54, f"[1/5] Threads - {len(queries)} queries")
        comments, info = collect(client, queries, log=self._log)
        self._emit(55, f"      threads: {len(comments)} posts.")
        info["comments"] = len(comments)
        return comments, info

    # ------------------------------------------------------------------ run

    def run(self, tag: Optional[str] = None) -> Dict[str, Any]:
        if self.analyzer_warning:
            self._emit(0, self.analyzer_warning)
        comments, fetch_meta = self.fetch()
        if not comments:
            raise RuntimeError(
                "No comments collected from any source. Check credentials for the sources you "
                "selected, or run with --source fixtures."
            )

        self._emit(60, "[2/5] Filtering for relevance to stevia tomato / competitors / category...")
        outcome = self.scorer.filter(comments)
        summary = outcome.summary()
        self._log(
            f"      kept {summary['relevant']}/{summary['fetched']} "
            f"({summary['keep_rate'] * 100:.1f}%) | buckets: {summary['buckets']}"
        )
        if not outcome.comments:
            raise RuntimeError(
                "Every comment was filtered out. Lower --threshold or widen the terms in config/taxonomy.json."
            )

        self._emit(70, f"[3/5] Analyzing with the '{self.analyzer.name}' analyzer...")
        analyses = self.analyzer.analyze(outcome.comments, outcome.results)
        stats = overall_stats(analyses)
        self._log(
            f"      sentiment {stats['avg_sentiment']:+.3f} | "
            f"qualified leads {stats['qualified_leads']}/{stats['analyzed_comments']}"
        )

        self._emit(85, "[4/5] Building customer segments...")
        profiles = build_segments(analyses, self.taxonomy, min_size=self.config.min_segment_size)
        for profile in profiles:
            self._log(
                f"      - {profile.name}: {profile.size} comments "
                f"({profile.share * 100:.1f}%), {profile.qualified_leads} qualified"
            )

        self._emit(93, "[5/5] Generating recommendations...")
        recommendations = build_recommendations(profiles)
        notes = strategic_notes(stats, profiles)

        run_meta = {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "sources": list(self.config.sources),
            "analyzer": self.analyzer.name,
            "videos": fetch_meta.get("videos", 0),
            "queries": fetch_meta.get("queries", []),
            "quota": fetch_meta.get("quota"),
            # Per-source counts and any "skipped: no credentials" reasons, so a
            # partial run is auditable rather than silently short.
            "per_source": fetch_meta.get("per_source", {}),
            "relevance_threshold": self.config.relevance_threshold,
        }

        self._emit(96, "      writing report...")
        paths = report_writer.write_report(
            stats=stats,
            filter_summary=summary,
            profiles=profiles,
            recommendations=recommendations,
            notes=notes,
            analyses=analyses,
            run_meta=run_meta,
            output_dir=self.config.output_dir,
            tag=tag,
        )

        return {
            "stats": stats,
            "filter_summary": summary,
            "profiles": profiles,
            "recommendations": recommendations,
            "notes": notes,
            "analyses": analyses,
            "run_meta": run_meta,
            "paths": paths,
        }

"""Output writers: JSON (machine), CSV (inspectable), Markdown (presentable)."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence

from .config import OUTPUT_DIR
from .textutil import truncate

BAR_FULL = "█"
BAR_EMPTY = "░"


def _bar(value: float, width: int = 20) -> str:
    filled = int(round(max(0.0, min(1.0, value)) * width))
    return BAR_FULL * filled + BAR_EMPTY * (width - filled)


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def write_json(payload: Dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return path


def write_comments_csv(analyses: Sequence[Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "comment_id", "segment", "lead_grade", "lead_score", "sentiment_label",
        "sentiment_score", "intent", "topics", "relevance_bucket", "relevance_score",
        "like_count", "author", "platform", "container_title", "permalink", "published_at", "text",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in analyses:
            record = row.to_dict()
            record["topics"] = "|".join(record.get("topics", []))
            writer.writerow(record)
    return path


def build_markdown(
    *,
    stats: Dict[str, Any],
    filter_summary: Dict[str, Any],
    profiles: Sequence[Any],
    recommendations: Sequence[Any],
    notes: Sequence[str],
    run_meta: Dict[str, Any],
) -> str:
    lines: List[str] = []
    add = lines.append

    add("# Zorvex · SNS Listening Report")
    add("")
    add("**HANGOOD Stevia Tomato — YouTube comment intelligence**  ")
    sources = run_meta.get("sources") or [run_meta.get("source", "")]
    add(f"Generated {run_meta.get('generated_at', '')} · sources: `{' + '.join(s for s in sources if s)}` · analyzer: `{run_meta.get('analyzer', '')}`")
    add("")
    add("> Segments are seeded from Zorvex's own answers (Q&A 2026-08-27, A3) and leads are graded against")
    add("> Zorvex's own criteria (A4). This report measures those stated targets against real observed conversation.")
    add("")

    # ------------------------------------------------------------- funnel
    add("## 1 · Collection funnel")
    add("")
    add("| Stage | Count |")
    add("|---|---:|")
    add(f"| Videos searched | {run_meta.get('videos', 0)} |")
    add(f"| Comments fetched | {filter_summary.get('fetched', 0)} |")
    add(f"| Relevant after filtering | {filter_summary.get('relevant', 0)} |")
    add(f"| Dropped — off topic | {filter_summary.get('dropped_off_topic', 0)} |")
    add(f"| Dropped — spam / too short | {filter_summary.get('dropped_spam_or_too_short', 0)} |")
    add(f"| **Keep rate** | **{filter_summary.get('keep_rate', 0) * 100:.1f}%** |")
    add("")

    platform_mix = stats.get("platform_mix", {})
    if len(platform_mix) > 1:
        add("**Where the relevant comments came from:**")
        add("")
        add("| Platform | Comments |")
        add("|---|---:|")
        for platform, count in platform_mix.items():
            add(f"| {platform} | {count} |")
        add("")

    buckets = filter_summary.get("buckets", {})
    if buckets:
        add("**Relevance mix** — what the surviving comments are about:")
        add("")
        add("| Bucket | Comments |")
        add("|---|---:|")
        for bucket, count in buckets.items():
            add(f"| {bucket} | {count} |")
        add("")

    # ------------------------------------------------------------ overview
    add("## 2 · Overall signal")
    add("")
    if stats:
        mix = stats.get("sentiment_mix", {})
        total = max(1, stats.get("analyzed_comments", 1))
        add(f"- **Analyzed:** {stats.get('analyzed_comments', 0)} comments")
        add(f"- **Average sentiment:** {stats.get('avg_sentiment', 0):+.3f}")
        add(f"- **Positive / neutral / negative:** {mix.get('positive', 0)} / {mix.get('neutral', 0)} / {mix.get('negative', 0)}")
        add(f"- **Qualified leads (grade A/B):** {stats.get('qualified_leads', 0)} ({stats.get('qualified_leads', 0) / total * 100:.1f}%)")
        add("")
        add("**Lead grade distribution** (graded against A4's criteria):")
        add("")
        add("| Grade | Meaning | Count |")
        add("|---|---|---:|")
        meanings = {
            "A": "Strong fit + clear buy/re-buy intent",
            "B": "Good category fit, some intent",
            "C": "Interested but unqualified",
            "D": "Low relevance or price-only interest",
        }
        for grade, count in stats.get("lead_grades", {}).items():
            add(f"| {grade} | {meanings.get(grade, '')} | {count} |")
        add("")
        topics = stats.get("top_topics", [])
        if topics:
            add("**What the conversation is actually about:**")
            add("")
            top_count = max((c for _, c in topics), default=1)
            for topic, count in topics:
                add(f"- `{topic:<13}` {_bar(count / top_count)} {count}")
            add("")

    # ------------------------------------------------------------ segments
    add("## 3 · Customer segments")
    add("")
    if not profiles:
        add("_No segments formed — not enough relevant comments._")
        add("")
    for profile in profiles:
        add(f"### {profile.name} · {profile.name_ko}")
        add("")
        add(
            f"**{profile.size} comments ({profile.share * 100:.1f}%)** · "
            f"sentiment {profile.avg_sentiment:+.2f} · "
            f"avg lead score {profile.avg_lead_score} · "
            f"**{profile.qualified_leads} qualified (A/B)** · "
            f"stated lead value: `{profile.lead_value}`"
        )
        add("")
        add(f"_{profile.description}_")
        add("")
        if profile.top_topics:
            add("| Top topics | " + " · ".join(f"{t} ({c})" for t, c in profile.top_topics) + " |")
            add("|---|---|")
            add("| Top keywords | " + " · ".join(f"{k} ({c})" for k, c in profile.top_keywords[:8]) + " |")
            intent = profile.intent_mix
            add(
                "| Purchase intent | "
                f"repeat {intent.get('repeat', 0)} · intent {intent.get('intent', 0)} · "
                f"curious {intent.get('curious', 0)} · none {intent.get('none', 0)} |"
            )
            add("")
        if profile.sample_quotes:
            add("**Representative comments:**")
            add("")
            for quote in profile.sample_quotes:
                marker = {"positive": "🟢", "negative": "🔴", "neutral": "⚪"}.get(quote["sentiment"], "⚪")
                # A clickable source link makes every quoted number checkable -
                # the difference between a claim and evidence at a pitch.
                link = f" · [open ↗]({quote['permalink']})" if quote.get("permalink") else ""
                source = f" · _{quote['source']}_" if quote.get("source") else ""
                translation = (
                    f"  <br/>  ↳ *translated (KO): {quote['text_ko']}*" if quote.get("text_ko") else ""
                )
                add(
                    f"- {marker} \"{quote['text']}\"  "
                    f"<br/>  ↳ `{quote.get('platform', '')}` · grade **{quote['lead_grade']}** "
                    f"({quote['lead_score']}) · intent `{quote['intent']}` · {quote['likes']} likes"
                    f"{source}{link}{translation}"
                )
            add("")

    # ----------------------------------------------------- recommendations
    add("## 4 · Marketing recommendations")
    add("")
    add("_Ranked by opportunity — qualified leads weighted above raw segment size, per A4:_")
    add("_\"we do not want many leads — we want the leads most likely to turn into real sales.\"_")
    add("")
    for rec in recommendations:
        add(f"### {rec.priority}. {rec.segment_name}")
        add("")
        add(f"| | |")
        add(f"|---|---|")
        add(f"| **Priority score** | {rec.priority_score} |")
        add(f"| **Size / qualified** | {rec.size} comments · {rec.qualified_leads} qualified |")
        add(f"| **Channel** | {rec.channel} |")
        add(f"| **Message angle** | {rec.message_angle} |")
        add(f"| **Content idea** | {rec.content_idea} |")
        add(f"| **Why this rank** | {rec.rationale} |")
        if rec.objection_to_address:
            add(f"| **⚠ Objection to fix** | {rec.objection_to_address} |")
        add("")
        if rec.evidence_quote:
            link = f" [open ↗]({rec.evidence_permalink})" if rec.evidence_permalink else ""
            add(f"> Evidence: \"{truncate(rec.evidence_quote, 160)}\"{link}")
            if rec.evidence_quote_ko:
                add(f"> *translated (KO): {truncate(rec.evidence_quote_ko, 160)}*")
            add("")

    # -------------------------------------------------------------- notes
    if notes:
        add("## 5 · Strategic notes")
        add("")
        for note in notes:
            add(f"- {note}")
        add("")

    add("---")
    add("")
    add("### How to read this")
    add("")
    add("This does **not** tell Zorvex who their customer is — they already answered that (A3).")
    add("It measures **how much real conversation sits behind each stated target**, **which of those")
    add("conversations contain qualified leads by their own definition (A4)**, and **what to say to each**.")
    add("")
    quota = run_meta.get("quota")
    if quota:
        add(
            f"_API usage this run: {quota.get('api_calls', 0)} calls, "
            f"{quota.get('quota_units_used', 0)} of 10,000 daily quota units._"
        )
    return "\n".join(lines)


def write_report(
    *,
    stats: Dict[str, Any],
    filter_summary: Dict[str, Any],
    profiles: Sequence[Any],
    recommendations: Sequence[Any],
    notes: Sequence[str],
    analyses: Sequence[Any],
    run_meta: Dict[str, Any],
    output_dir: Path | None = None,
    tag: str | None = None,
) -> Dict[str, Path]:
    out_dir = output_dir or OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = tag or _timestamp()

    markdown = build_markdown(
        stats=stats,
        filter_summary=filter_summary,
        profiles=profiles,
        recommendations=recommendations,
        notes=notes,
        run_meta=run_meta,
    )

    md_path = out_dir / f"report_{stamp}.md"
    md_path.write_text(markdown, encoding="utf-8")

    json_path = write_json(
        {
            "run": run_meta,
            "collection": filter_summary,
            "overall": stats,
            "segments": [p.to_dict() for p in profiles],
            "recommendations": [r.to_dict() for r in recommendations],
            "strategic_notes": list(notes),
        },
        out_dir / f"analysis_{stamp}.json",
    )

    csv_path = write_comments_csv(analyses, out_dir / f"comments_{stamp}.csv")

    latest = out_dir / "latest_report.md"
    latest.write_text(markdown, encoding="utf-8")

    return {"markdown": md_path, "json": json_path, "csv": csv_path, "latest": latest}

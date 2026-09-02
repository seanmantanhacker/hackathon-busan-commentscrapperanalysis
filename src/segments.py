"""Aggregate per-comment analysis into named customer segments.

The segments themselves are NOT discovered from scratch - Zorvex already told
us who they target (Q&A A3: K-Food / Healthy Food / Diet / Wellness / Premium
Fruit / Sweet Tomato). What this module produces is the part they do not have:
how big each of those segments actually is in observed conversation, how it
feels, what it talks about, and how many qualified leads sit inside it.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Sequence

from .textutil import keywords, truncate


@dataclass
class SegmentProfile:
    segment_id: str
    name: str
    name_ko: str
    description: str
    lead_value: str
    size: int
    share: float
    avg_sentiment: float
    sentiment_mix: Dict[str, int]
    top_topics: List[tuple]
    top_keywords: List[tuple]
    intent_mix: Dict[str, int]
    lead_grades: Dict[str, int]
    qualified_leads: int
    avg_lead_score: float
    sample_quotes: List[Dict[str, Any]]
    top_objection: str | None = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _sentiment_mix(rows: Sequence[Any]) -> Dict[str, int]:
    counter = Counter(r.sentiment_label for r in rows)
    return {label: counter.get(label, 0) for label in ("positive", "neutral", "negative")}


def _pick_quotes(rows: Sequence[Any], limit: int = 3) -> List[Dict[str, Any]]:
    """Representative quotes: prefer high-signal comments, keep one negative.

    Showing only glowing quotes would make the dashboard useless for deciding
    what to fix, so the most negative comment is always kept if one exists.
    """
    if not rows:
        return []
    ranked = sorted(rows, key=lambda r: (r.lead_score, r.like_count), reverse=True)
    chosen = list(ranked[: max(1, limit - 1)])

    negatives = [r for r in rows if r.sentiment_label == "negative"]
    if negatives:
        worst = min(negatives, key=lambda r: r.sentiment_score)
        if worst.comment_id not in {c.comment_id for c in chosen}:
            chosen.append(worst)
    elif len(ranked) > len(chosen):
        chosen.append(ranked[len(chosen)])

    return [
        {
            "text": truncate(r.text, 200),
            "sentiment": r.sentiment_label,
            "sentiment_score": r.sentiment_score,
            "intent": r.intent,
            "lead_grade": r.lead_grade,
            "lead_score": r.lead_score,
            "likes": r.like_count,
            "source": truncate(r.container_title, 70),
            "platform": r.platform,
            "permalink": r.permalink,
        }
        for r in chosen[:limit]
    ]


def build_segments(
    analyses: Sequence[Any],
    taxonomy: Dict[str, Any],
    *,
    min_size: int = 1,
) -> List[SegmentProfile]:
    total = len(analyses)
    if not total:
        return []

    definitions = {s["id"]: s for s in taxonomy["segments"]}
    definitions["unsegmented"] = {
        "id": "unsegmented",
        "name": "Unsegmented",
        "name_ko": "미분류",
        "description": "Relevant to the category but no segment keyword matched - review these to grow the taxonomy.",
        "lead_value": "unknown",
    }

    grouped: Dict[str, List[Any]] = {}
    for row in analyses:
        grouped.setdefault(row.segment, []).append(row)

    profiles: List[SegmentProfile] = []
    for segment_id, rows in grouped.items():
        if len(rows) < min_size:
            continue
        definition = definitions.get(segment_id, definitions["unsegmented"])

        topic_counter: Counter = Counter()
        keyword_counter: Counter = Counter()
        for row in rows:
            topic_counter.update(row.topics)
            keyword_counter.update(keywords(row.normalized_text))

        intent_counter = Counter(r.intent for r in rows)
        grade_counter = Counter(r.lead_grade for r in rows)
        qualified = sum(1 for r in rows if r.lead_grade in ("A", "B"))

        negatives = [r for r in rows if r.sentiment_label == "negative"]
        objection = None
        if negatives:
            objection_topics: Counter = Counter()
            for row in negatives:
                objection_topics.update(row.topics)
            if objection_topics:
                objection = objection_topics.most_common(1)[0][0]

        profiles.append(
            SegmentProfile(
                segment_id=segment_id,
                name=definition["name"],
                name_ko=definition.get("name_ko", ""),
                description=definition.get("description", ""),
                lead_value=definition.get("lead_value", "unknown"),
                size=len(rows),
                share=round(len(rows) / total, 4),
                avg_sentiment=round(sum(r.sentiment_score for r in rows) / len(rows), 3),
                sentiment_mix=_sentiment_mix(rows),
                top_topics=topic_counter.most_common(5),
                top_keywords=keyword_counter.most_common(10),
                intent_mix={k: intent_counter.get(k, 0) for k in ("repeat", "intent", "curious", "none")},
                lead_grades={g: grade_counter.get(g, 0) for g in ("A", "B", "C", "D")},
                qualified_leads=qualified,
                avg_lead_score=round(sum(r.lead_score for r in rows) / len(rows), 1),
                sample_quotes=_pick_quotes(rows),
                top_objection=objection,
            )
        )

    profiles.sort(key=lambda p: (p.qualified_leads, p.size), reverse=True)
    return profiles


def overall_stats(analyses: Sequence[Any]) -> Dict[str, Any]:
    if not analyses:
        return {}
    topic_counter: Counter = Counter()
    for row in analyses:
        topic_counter.update(row.topics)

    sentiments = Counter(r.sentiment_label for r in analyses)
    grades = Counter(r.lead_grade for r in analyses)
    intents = Counter(r.intent for r in analyses)
    buckets = Counter(r.relevance_bucket for r in analyses)
    platforms = Counter(r.platform for r in analyses)

    return {
        "analyzed_comments": len(analyses),
        "avg_sentiment": round(sum(r.sentiment_score for r in analyses) / len(analyses), 3),
        "sentiment_mix": {k: sentiments.get(k, 0) for k in ("positive", "neutral", "negative")},
        "lead_grades": {k: grades.get(k, 0) for k in ("A", "B", "C", "D")},
        "qualified_leads": sum(grades.get(g, 0) for g in ("A", "B")),
        "intent_mix": {k: intents.get(k, 0) for k in ("repeat", "intent", "curious", "none")},
        "relevance_buckets": dict(buckets.most_common()),
        "platform_mix": dict(platforms.most_common()),
        "top_topics": topic_counter.most_common(7),
    }

"""Relevance filtering: decide which fetched comments are worth analyzing.

YouTube search returns a lot of noise - a video about "cemilan sehat" will have
comments about unrelated snacks, giveaway spam, and channel promotion. This
module scores every comment against the taxonomy and assigns it a bucket, so
downstream analysis only sees comments that actually relate to Zorvex's
product, its competitors, or its target category.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence

from .textutil import matched_terms, normalize

# Bucket priority, most product-specific first.
BUCKETS = ("brand", "product_core", "competitor", "category", "off_topic")

DEFAULT_THRESHOLD = 1.0


@dataclass
class RelevanceResult:
    score: float
    bucket: str
    matched: Dict[str, List[str]] = field(default_factory=dict)
    is_spam: bool = False
    normalized_text: str = ""

    @property
    def is_relevant(self) -> bool:
        return self.bucket != "off_topic" and not self.is_spam


class RelevanceScorer:
    def __init__(self, taxonomy: Dict[str, Any], *, threshold: float = DEFAULT_THRESHOLD) -> None:
        self.threshold = threshold
        self.groups = {
            "brand": (taxonomy["brand"]["terms"], float(taxonomy["brand"]["weight"])),
            "product_core": (taxonomy["product_core"]["terms"], float(taxonomy["product_core"]["weight"])),
            "competitor": (taxonomy["competitor"]["terms"], float(taxonomy["competitor"]["weight"])),
            "category": (taxonomy["category"]["terms"], float(taxonomy["category"]["weight"])),
        }
        self.disqualifiers: Sequence[str] = taxonomy.get("disqualifiers", {}).get("terms", [])

    def score(self, text: str) -> RelevanceResult:
        norm = normalize(text)
        if not norm:
            return RelevanceResult(0.0, "off_topic", {}, False, norm)

        matched: Dict[str, List[str]] = {}
        total = 0.0
        for group, (terms, weight) in self.groups.items():
            hits = matched_terms(norm, terms)
            if hits:
                matched[group] = hits
                # Diminishing returns: repeating category words shouldn't
                # outrank one precise product mention.
                total += weight * (1 + 0.25 * (len(hits) - 1))

        spam_hits = matched_terms(norm, self.disqualifiers)
        # Very short comments carry no analyzable signal even if a term matched.
        too_short = len(norm.split()) < 3
        is_spam = bool(spam_hits) or too_short
        if spam_hits:
            matched["disqualifier"] = spam_hits

        bucket = "off_topic"
        if total >= self.threshold:
            for candidate in ("brand", "product_core", "competitor", "category"):
                if candidate in matched:
                    bucket = candidate
                    break

        return RelevanceResult(round(total, 3), bucket, matched, is_spam, norm)

    def filter(self, comments: Sequence[Any]) -> "FilterOutcome":
        kept: List[Any] = []
        results: List[RelevanceResult] = []
        dropped_offtopic = 0
        dropped_spam = 0

        for comment in comments:
            result = self.score(getattr(comment, "text", "") or "")
            if result.is_relevant:
                kept.append(comment)
                results.append(result)
            elif result.is_spam and result.score >= self.threshold:
                dropped_spam += 1
            else:
                dropped_offtopic += 1

        return FilterOutcome(
            comments=kept,
            results=results,
            total_input=len(comments),
            dropped_offtopic=dropped_offtopic,
            dropped_spam=dropped_spam,
        )


@dataclass
class FilterOutcome:
    comments: List[Any]
    results: List[RelevanceResult]
    total_input: int
    dropped_offtopic: int
    dropped_spam: int

    @property
    def kept(self) -> int:
        return len(self.comments)

    @property
    def keep_rate(self) -> float:
        return (self.kept / self.total_input) if self.total_input else 0.0

    def bucket_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for result in self.results:
            counts[result.bucket] = counts.get(result.bucket, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))

    def summary(self) -> Dict[str, Any]:
        return {
            "fetched": self.total_input,
            "relevant": self.kept,
            "keep_rate": round(self.keep_rate, 3),
            "dropped_off_topic": self.dropped_offtopic,
            "dropped_spam_or_too_short": self.dropped_spam,
            "buckets": self.bucket_counts(),
        }

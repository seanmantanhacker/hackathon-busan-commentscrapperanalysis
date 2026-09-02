"""Per-comment analysis: sentiment, topic tags, purchase intent, lead quality.

The baseline analyzer is rules + lexicon based on purpose:
  - it is deterministic, so the same demo produces the same numbers on stage;
  - it needs no second API key or network call;
  - every number can be traced back to a matched term when a mentor asks "why".

`llm_analyze.py` provides an optional upgrade path that swaps this out for
Claude while keeping the same output shape.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Sequence

from .textutil import contains_term, keywords, matched_terms, normalize

SENTIMENT_LABELS = ("positive", "neutral", "negative")
INTENT_LEVELS = ("repeat", "intent", "curious", "none")

# A4's rubric, ordered strongest first.
INTENT_WEIGHT = {"repeat": 3.0, "intent": 2.0, "curious": 1.0, "none": 0.0}


@dataclass
class CommentAnalysis:
    comment_id: str
    text: str
    normalized_text: str
    relevance_score: float
    relevance_bucket: str
    matched_terms: Dict[str, List[str]]
    sentiment_score: float
    sentiment_label: str
    topics: List[str]
    intent: str
    segment: str
    segment_scores: Dict[str, float]
    lead_score: float
    lead_grade: str
    like_count: int = 0
    platform: str = "youtube"
    container_title: str = ""
    permalink: str = ""
    author: str = ""
    published_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RulesAnalyzer:
    """Lexicon-driven analyzer. See module docstring for why this is the default."""

    name = "rules"

    def __init__(self, taxonomy: Dict[str, Any], lexicon: Dict[str, Any]) -> None:
        self.taxonomy = taxonomy
        self.positive: Dict[str, float] = lexicon["positive"]
        self.negative: Dict[str, float] = lexicon["negative"]
        self.negators: List[str] = lexicon["negators"]
        self.intensifiers: Dict[str, float] = lexicon["intensifiers"]
        self.topic_lexicon: Dict[str, List[str]] = {
            k: v for k, v in taxonomy["topics"].items() if k != "comment"
        }
        self.intent_lexicon: Dict[str, List[str]] = {
            k: v for k, v in taxonomy["purchase_intent"].items() if k != "comment"
        }
        self.segments: List[Dict[str, Any]] = taxonomy["segments"]

    # ------------------------------------------------------------- sentiment

    def sentiment(self, norm: str) -> tuple[float, str]:
        """Polarity in [-1, 1] with negation and intensifier handling.

        Negation flips the polarity of a term when a negator appears in the
        three tokens before it - enough to catch "gak enak" / "not worth it"
        without a parser.
        """
        tokens = norm.split()
        if not tokens:
            return 0.0, "neutral"

        total = 0.0
        matches = 0

        for lexicon, sign in ((self.positive, 1.0), (self.negative, 1.0)):
            for term, weight in lexicon.items():
                if not contains_term(norm, term):
                    continue
                term_head = term.split()[0]
                try:
                    idx = tokens.index(term_head)
                except ValueError:
                    idx = 0

                value = weight * sign
                window = tokens[max(0, idx - 3) : idx]
                if any(neg in window for neg in self.negators):
                    value = -value * 0.9
                for intensifier, factor in self.intensifiers.items():
                    if intensifier in tokens[idx : idx + 3] or intensifier in window:
                        value *= factor
                        break

                total += value
                matches += 1

        if not matches:
            return 0.0, "neutral"

        # sqrt damping: a comment with 6 positive words isn't 6x as positive
        # as one with a single strong word.
        score = total / math.sqrt(matches)
        score = max(-1.0, min(1.0, score / 1.5))

        if score >= 0.15:
            label = "positive"
        elif score <= -0.15:
            label = "negative"
        else:
            label = "neutral"
        return round(score, 3), label

    # ---------------------------------------------------------------- topics

    def topics(self, norm: str) -> List[str]:
        found = [topic for topic, terms in self.topic_lexicon.items() if matched_terms(norm, terms)]
        return found

    # ---------------------------------------------------------------- intent

    def intent(self, norm: str) -> str:
        for level in INTENT_LEVELS:
            terms = self.intent_lexicon.get(level, [])
            if terms and matched_terms(norm, terms):
                return level
        return "none"

    # -------------------------------------------------------------- segments

    def segment(self, norm: str, topics: Sequence[str]) -> tuple[str, Dict[str, float]]:
        scores: Dict[str, float] = {}
        for segment in self.segments:
            hits = matched_terms(norm, segment["keywords"])
            if hits:
                scores[segment["id"]] = round(1.0 + 0.3 * (len(hits) - 1), 3)

        # Topic-based nudges for comments that show interest without using an
        # explicit segment keyword.
        if "health" in topics:
            scores["health_diet_seeker"] = scores.get("health_diet_seeker", 0.0) + 0.5
        if "price" in topics and "taste" not in topics:
            scores["price_sensitive"] = scores.get("price_sensitive", 0.0) + 0.4

        if not scores:
            return "unsegmented", {}
        primary = max(scores.items(), key=lambda kv: kv[1])[0]
        return primary, dict(sorted(scores.items(), key=lambda kv: -kv[1]))

    # ------------------------------------------------------------ lead score

    def lead_score(
        self,
        *,
        segment: str,
        sentiment_score: float,
        intent: str,
        topics: Sequence[str],
        relevance_bucket: str,
        like_count: int,
    ) -> tuple[float, str]:
        """Score 0-100 against the five B2C criteria Zorvex gave in Q&A A4.

        A4: (1) already interested in health/diet/K-Food/premium, (2) values
        taste and quality over price, (3) shows buy/re-buy intent, (4) buys food
        online, (5) likely to buy repeatedly rather than out of curiosity.
        """
        score = 0.0

        # (1) Pre-existing category interest - worth the most.
        segment_value = {
            "kfood_enthusiast": 30.0,
            "health_diet_seeker": 30.0,
            "premium_fruit_buyer": 30.0,
            "wellness_clean_eating": 22.0,
            "family_everyday_shopper": 18.0,
            "price_sensitive": 4.0,
            "unsegmented": 8.0,
        }
        score += segment_value.get(segment, 8.0)

        # (2) Values taste/quality over price.
        if "taste" in topics or "freshness" in topics:
            score += 12.0
        if "price" in topics and segment == "price_sensitive":
            score -= 10.0

        # (3) + (5) Stated buy / re-buy intent.
        score += INTENT_WEIGHT[intent] * 8.0

        # (4) Signals of actually transacting online.
        if "availability" in topics or "delivery" in topics:
            score += 10.0

        # Sentiment as a modifier, not a driver.
        score += sentiment_score * 10.0

        # Product-specific mentions beat generic category chatter.
        bucket_bonus = {"brand": 10.0, "product_core": 8.0, "competitor": 5.0, "category": 0.0}
        score += bucket_bonus.get(relevance_bucket, 0.0)

        # Community endorsement - a liked comment reflects more than one person.
        score += min(6.0, math.log1p(max(0, like_count)) * 2.0)

        score = max(0.0, min(100.0, score))

        if score >= 65:
            grade = "A"
        elif score >= 45:
            grade = "B"
        elif score >= 28:
            grade = "C"
        else:
            grade = "D"
        return round(score, 1), grade

    # ----------------------------------------------------------------- entry

    def analyze_one(self, comment: Any, relevance: Any) -> CommentAnalysis:
        norm = relevance.normalized_text or normalize(comment.text)
        sentiment_score, sentiment_label = self.sentiment(norm)
        topic_tags = self.topics(norm)
        intent = self.intent(norm)
        segment, segment_scores = self.segment(norm, topic_tags)
        lead_score, lead_grade = self.lead_score(
            segment=segment,
            sentiment_score=sentiment_score,
            intent=intent,
            topics=topic_tags,
            relevance_bucket=relevance.bucket,
            like_count=getattr(comment, "like_count", 0),
        )

        return CommentAnalysis(
            comment_id=comment.comment_id,
            text=comment.text,
            normalized_text=norm,
            relevance_score=relevance.score,
            relevance_bucket=relevance.bucket,
            matched_terms=relevance.matched,
            sentiment_score=sentiment_score,
            sentiment_label=sentiment_label,
            topics=topic_tags,
            intent=intent,
            segment=segment,
            segment_scores=segment_scores,
            lead_score=lead_score,
            lead_grade=lead_grade,
            like_count=getattr(comment, "like_count", 0),
            platform=getattr(comment, "platform", "youtube"),
            container_title=getattr(comment, "container_title", ""),
            permalink=getattr(comment, "permalink", ""),
            author=getattr(comment, "author", ""),
            published_at=getattr(comment, "published_at", ""),
        )

    def analyze(self, comments: Sequence[Any], results: Sequence[Any]) -> List[CommentAnalysis]:
        return [self.analyze_one(c, r) for c, r in zip(comments, results)]

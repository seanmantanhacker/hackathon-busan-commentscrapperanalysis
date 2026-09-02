"""Optional Claude-assisted analyzer (`--analyzer llm`).

The rules analyzer is the baseline and the demo default because it is
deterministic and free. This module is the upgrade path: it sends batches of
comments to Claude for sentiment, topic, intent, and segment judgment, which
handles sarcasm, slang, and mixed-language comments that a lexicon misses.

It produces the exact same `CommentAnalysis` objects, so everything downstream
(segments, recommendations, report) is unchanged. Any failure falls back to the
rules result for that batch rather than aborting the run.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Sequence

from .analyze import CommentAnalysis, RulesAnalyzer
from .config import get_anthropic_key

MODEL = "claude-sonnet-5"
BATCH_SIZE = 20

SYSTEM_PROMPT = """You analyze Indonesian, Korean, and English YouTube comments for Zorvex, \
a Korean company selling HANGOOD stevia tomatoes (a premium sweet tomato) in Indonesia.

For each comment return:
- sentiment_score: float -1.0 (very negative) to 1.0 (very positive)
- sentiment_label: "positive" | "neutral" | "negative"
- topics: subset of ["taste","price","health","packaging","availability","freshness","delivery"]
- intent: "repeat" (says they buy repeatedly/again) | "intent" (says they will buy) | \
"curious" (asks where/how much) | "none"
- segment: one of ["kfood_enthusiast","health_diet_seeker","premium_fruit_buyer",\
"wellness_clean_eating","family_everyday_shopper","price_sensitive","unsegmented"]

Handle Indonesian slang (enak, mantul, gak worth, kemahalan, nagih) and sarcasm. \
Return ONLY a JSON array, one object per comment, each with an "index" field matching \
the input index. No prose."""


class LLMAnalyzer:
    name = "llm"

    def __init__(self, taxonomy: Dict[str, Any], lexicon: Dict[str, Any]) -> None:
        api_key = get_anthropic_key()
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        try:
            import anthropic  # noqa: F401
        except ImportError as exc:
            raise RuntimeError("`pip install anthropic` required for --analyzer llm") from exc

        from anthropic import Anthropic

        self.client = Anthropic(api_key=api_key)
        self.fallback = RulesAnalyzer(taxonomy, lexicon)

    def _call(self, batch: Sequence[Any]) -> List[Dict[str, Any]]:
        payload = [{"index": i, "text": c.text[:600]} for i, c in enumerate(batch)]
        message = self.client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        )
        text = "".join(block.text for block in message.content if block.type == "text").strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            text = text[4:] if text.startswith("json") else text
        return json.loads(text)

    def analyze(self, comments: Sequence[Any], results: Sequence[Any]) -> List[CommentAnalysis]:
        analyses: List[CommentAnalysis] = []

        for start in range(0, len(comments), BATCH_SIZE):
            batch = list(comments[start : start + BATCH_SIZE])
            batch_results = list(results[start : start + BATCH_SIZE])

            try:
                judgments = {int(row["index"]): row for row in self._call(batch)}
            except Exception as exc:  # noqa: BLE001 - degrade, don't abort
                print(f"  ! LLM batch failed ({exc}); using rules for these {len(batch)} comments.")
                judgments = {}

            for i, (comment, relevance) in enumerate(zip(batch, batch_results)):
                base = self.fallback.analyze_one(comment, relevance)
                judgment = judgments.get(i)
                if judgment:
                    base.sentiment_score = float(judgment.get("sentiment_score", base.sentiment_score))
                    base.sentiment_label = judgment.get("sentiment_label", base.sentiment_label)
                    base.topics = list(judgment.get("topics", base.topics))
                    base.intent = judgment.get("intent", base.intent)
                    base.segment = judgment.get("segment", base.segment)
                    # Re-grade with the LLM's judgments so lead scores stay consistent.
                    base.lead_score, base.lead_grade = self.fallback.lead_score(
                        segment=base.segment,
                        sentiment_score=base.sentiment_score,
                        intent=base.intent,
                        topics=base.topics,
                        relevance_bucket=base.relevance_bucket,
                        like_count=base.like_count,
                    )
                analyses.append(base)

        return analyses

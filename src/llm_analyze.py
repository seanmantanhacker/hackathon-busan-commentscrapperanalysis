"""Optional Gemini-assisted analyzer (`--analyzer llm`).

The rules analyzer is the baseline and the demo default because it is
deterministic and free. This module is the upgrade path: it sends batches of
comments to Gemini for sentiment, topic, intent, and segment judgment, which
handles sarcasm, slang, and mixed-language comments that a lexicon misses.

It produces the exact same `CommentAnalysis` objects, so everything downstream
(segments, recommendations, report) is unchanged. Any failure falls back to the
rules result for that batch rather than aborting the run.

Calls rotate through `get_gemini_models()` batch by batch, and fail over to the
next model in the list if one errors (bad name, rate-limited, etc.) - this
spreads load across each model's separate free-tier quota instead of hammering
a single one.
"""

from __future__ import annotations

import itertools
import json
from typing import Any, Callable, Dict, List, Sequence

from .analyze import CommentAnalysis, RulesAnalyzer
from .config import get_gemini_key, get_gemini_models

BATCH_SIZE = 20

# The SDK's own default is no timeout at all (a stalled connection hangs
# forever) plus up to 5 retries with backoff up to 60s between them - on a
# flaky/rate-limited model that can block for many minutes before we ever get
# a chance to rotate to the next model. A slow model should fail fast instead:
# one bounded attempt, then let the rotation in _call() try the next model -
# that is more useful than the SDK retrying the same overloaded model.
REQUEST_TIMEOUT_MS = 20_000
RETRY_ATTEMPTS = 1

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
        api_key = get_gemini_key()
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not set")
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise RuntimeError("`pip install google-genai` required for --analyzer llm") from exc

        self.client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=REQUEST_TIMEOUT_MS,
                retry_options=types.HttpRetryOptions(attempts=RETRY_ATTEMPTS),
            ),
        )
        self.models = get_gemini_models()
        self._model_cycle = itertools.cycle(self.models)
        self.fallback = RulesAnalyzer(taxonomy, lexicon)

    def _call(self, batch: Sequence[Any]) -> List[Dict[str, Any]]:
        payload = [{"index": i, "text": c.text[:600]} for i, c in enumerate(batch)]
        contents = json.dumps(payload, ensure_ascii=False)

        last_exc: Exception | None = None
        for _ in range(len(self.models)):
            model = next(self._model_cycle)
            try:
                response = self.client.models.generate_content(
                    model=model,
                    contents=contents,
                    config={
                        "system_instruction": SYSTEM_PROMPT,
                        "response_mime_type": "application/json",
                    },
                )
                text = (response.text or "").strip()
                if text.startswith("```"):
                    text = text.split("```")[1]
                    text = text[4:] if text.startswith("json") else text
                return json.loads(text)
            except Exception as exc:  # noqa: BLE001 - try the next model in rotation
                last_exc = exc
                continue

        assert last_exc is not None
        raise last_exc

    def analyze(
        self,
        comments: Sequence[Any],
        results: Sequence[Any],
        *,
        on_batch: Callable[[int, int], None] | None = None,
    ) -> List[CommentAnalysis]:
        analyses: List[CommentAnalysis] = []
        total_batches = max(1, (len(comments) + BATCH_SIZE - 1) // BATCH_SIZE)

        for batch_num, start in enumerate(range(0, len(comments), BATCH_SIZE), start=1):
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

            if on_batch:
                on_batch(batch_num, total_batches)

        return analyses

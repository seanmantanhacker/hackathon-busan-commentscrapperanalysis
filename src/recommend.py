"""Turn segment profiles into marketing recommendations.

Recommendations are rule-driven and grounded in what Zorvex actually told us:
  - A2  : the next 6 months are a channel-expansion window; awareness must keep
          pace with distribution or sales-per-store falls.
  - A3  : two audiences - B2B buyers (Fresh Food Buyer / Category Manager / MD)
          and B2C consumers matching six keywords.
  - A6  : fulfillment is being handed to distribution partners, so the open
          question is reach and conversion, not delivery.
  - A7  : stevia tomato barely exists as a category in Indonesia, so demand has
          to be created, not captured.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any, Dict, List, Sequence

# Per-segment playbook. Channel choices favour what Zorvex already uses
# (Instagram, TikTok, in-store tasting via SPG) plus the fresh-food platforms
# and premium marts named in A3/A7.
SEGMENT_PLAYBOOK: Dict[str, Dict[str, str]] = {
    "kfood_enthusiast": {
        "channel": "TikTok + Instagram Reels, with Korean-food creators",
        "angle": "Frame it as a genuine Korean product, not a generic tomato — the Korean origin IS the product story.",
        "content": "60-second 'Korean snack you've never tried' reel: unbox, taste reaction, explain what a stevia tomato is.",
        "why": "Category interest already exists and is Korea-led; the cheapest awareness to buy.",
    },
    "health_diet_seeker": {
        "channel": "Instagram Reels + fitness/diet creators, plus on-pack nutrition callouts",
        "angle": "Lead with the number: sweetness without the sugar load. Calories and sugar content up front.",
        "content": "'Snack under X kcal' series and a side-by-side vs. regular sweets; pin the nutrition panel.",
        "why": "The largest stated target in A3/A4 and the one most likely to repeat-buy.",
    },
    "premium_fruit_buyer": {
        "channel": "Premium mart in-store display + fresh-food platform listings + gifting/hampers push",
        "angle": "Position beside shine muscat and imported fruit, not beside ordinary tomatoes. Price is the quality signal.",
        "content": "Premium packaging shots, gift-box format, 'why it costs more' provenance story.",
        "why": "A4 criterion 2 — already pays above market for taste and quality.",
    },
    "wellness_clean_eating": {
        "channel": "Instagram carousel + long-form YouTube collaborations",
        "angle": "Whole-food, natural sweetness, lycopene/antioxidant story — ingredient transparency.",
        "content": "Recipe content: salads, infused water, healthy bekal ideas featuring the product.",
        "why": "Slower to convert but high share-rate; builds the category narrative Indonesia lacks.",
    },
    "family_everyday_shopper": {
        "channel": "In-store SPG tasting (already proven) + WhatsApp/community groups",
        "angle": "'The fruit your kids will actually finish' — solve a household problem, not a diet goal.",
        "content": "Tasting-booth script + bekal (lunchbox) ideas; multi-pack family value format.",
        "why": "SPG tasting is Zorvex's one proven tactic (A5 round 1); this segment is who it already converts.",
    },
    "price_sensitive": {
        "channel": "Do not spend paid budget here",
        "angle": "If addressed at all, use a small trial/single-serve SKU rather than discounting the main line.",
        "content": "Trial-size format at checkout; no promotional discounting of the premium line.",
        "why": "A4 explicitly names extreme price sensitivity as a LOW-quality lead — discounting to win them erodes the premium position.",
    },
    "unsegmented": {
        "channel": "Review before spending",
        "angle": "These comments matched the category but no segment keyword — read them to extend the taxonomy.",
        "content": "Manual review; add recurring terms to config/taxonomy.json and re-run.",
        "why": "A growing unsegmented bucket means the taxonomy is going stale.",
    },
}

# Objections mapped to the fix, per topic.
OBJECTION_PLAYBOOK: Dict[str, str] = {
    "price": "Price resistance is the top objection here. Answer it with cost-per-serving and the sugar comparison, not a discount.",
    "availability": "People want to buy but can't find it. This is a distribution/listing gap — prioritize stocking and put the store locator in bio.",
    "delivery": "Delivery concerns dominate. Lead with the 3PL partner's cold-chain guarantee now that fulfillment is being outsourced (A6).",
    "freshness": "Freshness doubt is the blocker. Show harvest-to-shelf timing and the cold chain explicitly.",
    "taste": "Taste expectations are being missed. Get the tasting/SPG script to set expectations before the first bite.",
    "packaging": "Packaging is drawing criticism — worth a design review before the channel expansion in A2 scales it up.",
    "health": "Health claims are being questioned. Publish the sugar/calorie panel and the stevia explanation prominently.",
}


@dataclass
class Recommendation:
    segment_id: str
    segment_name: str
    priority: int
    priority_score: float
    size: int
    share: float
    qualified_leads: int
    avg_sentiment: float
    channel: str
    message_angle: str
    content_idea: str
    rationale: str
    objection_to_address: str | None = None
    evidence_quote: str | None = None
    evidence_quote_ko: str | None = None
    evidence_permalink: str | None = None
    evidence_source: str | None = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _priority_score(profile: Any) -> float:
    """Rank segments by opportunity, not just by size.

    Qualified leads dominate deliberately: A4 says Zorvex does not want many
    leads, it wants the ones that convert. A negative-sentiment segment gets a
    small boost because an unaddressed objection is also an opportunity.
    """
    score = profile.qualified_leads * 5.0
    score += profile.size * 1.5
    score += profile.avg_lead_score * 0.4
    score += (profile.intent_mix.get("repeat", 0) * 4.0) + (profile.intent_mix.get("intent", 0) * 2.5)
    if profile.lead_value == "high":
        score *= 1.25
    elif profile.lead_value == "low":
        score *= 0.35
    if profile.avg_sentiment < -0.1:
        score += 5.0
    return round(score, 2)


def build_recommendations(profiles: Sequence[Any]) -> List[Recommendation]:
    scored = sorted(profiles, key=_priority_score, reverse=True)
    recommendations: List[Recommendation] = []

    for rank, profile in enumerate(scored, start=1):
        play = SEGMENT_PLAYBOOK.get(profile.segment_id, SEGMENT_PLAYBOOK["unsegmented"])
        objection = None
        if profile.top_objection:
            objection = OBJECTION_PLAYBOOK.get(
                profile.top_objection,
                f"Recurring negative sentiment around '{profile.top_objection}' — worth investigating.",
            )

        evidence = evidence_ko = evidence_link = evidence_source = None
        if profile.sample_quotes:
            top_quote = profile.sample_quotes[0]
            evidence = top_quote["text"]
            evidence_ko = top_quote.get("text_ko") or None
            evidence_link = top_quote.get("permalink") or None
            evidence_source = top_quote.get("source") or None

        recommendations.append(
            Recommendation(
                segment_id=profile.segment_id,
                segment_name=profile.name,
                priority=rank,
                priority_score=_priority_score(profile),
                size=profile.size,
                share=profile.share,
                qualified_leads=profile.qualified_leads,
                avg_sentiment=profile.avg_sentiment,
                channel=play["channel"],
                message_angle=play["angle"],
                content_idea=play["content"],
                rationale=play["why"],
                objection_to_address=objection,
                evidence_quote=evidence,
                evidence_quote_ko=evidence_ko,
                evidence_permalink=evidence_link,
                evidence_source=evidence_source,
            )
        )
    return recommendations


def strategic_notes(stats: Dict[str, Any], profiles: Sequence[Any]) -> List[str]:
    """Cross-segment observations worth saying out loud at the pitch."""
    notes: List[str] = []
    if not stats:
        return notes

    buckets = stats.get("relevance_buckets", {})
    core = buckets.get("product_core", 0) + buckets.get("brand", 0)
    category = buckets.get("category", 0)
    competitor = buckets.get("competitor", 0)
    total = max(1, stats.get("analyzed_comments", 1))

    if core / total < 0.1:
        notes.append(
            f"Category creation confirmed: only {core}/{total} comments mention the product category directly. "
            "This matches A7 — stevia tomato barely exists in Indonesia, so marketing has to create demand, "
            "not capture existing search. Target adjacent interest (health/diet/K-Food/premium fruit) instead of "
            "the product name."
        )
    if competitor > core:
        notes.append(
            f"Competitor and adjacent-category conversation ({competitor} comments) outweighs product conversation ({core}). "
            "The audience exists and is already talking — it just isn't talking about Zorvex yet."
        )

    intent = stats.get("intent_mix", {})
    curious = intent.get("curious", 0)
    if curious and curious >= intent.get("intent", 0):
        notes.append(
            f"{curious} comments ask where to buy or how much it costs. That is unconverted demand: a purchase path "
            "in the profile bio and a store locator would capture it with no additional ad spend."
        )

    negative_segments = [p for p in profiles if p.avg_sentiment < -0.1]
    if negative_segments:
        names = ", ".join(p.name for p in negative_segments)
        notes.append(f"Negative-leaning segment(s) to fix before scaling spend: {names}.")

    qualified = stats.get("qualified_leads", 0)
    notes.append(
        f"{qualified} of {total} analyzed comments graded A/B against Zorvex's own lead criteria (A4). "
        "That ratio — not raw comment volume — is the number to track month over month."
    )
    return notes

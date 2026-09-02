"""Shared text normalization and keyword matching.

Handles the three languages that show up in Indonesian YouTube comments about
Korean food products: Indonesian, English, and Korean. Word-boundary regex is
used for Latin script; Korean has no spaces between morphemes in the same way,
so substring matching is used there instead.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Dict, Iterable, List, Sequence, Tuple

_WS = re.compile(r"\s+")
_URL = re.compile(r"https?://\S+|www\.\S+")
_HTML = re.compile(r"<[^>]+>")
_EMOJI_ISH = re.compile(
    "[" "\U0001f300-\U0001faff" "\U00002600-\U000027bf" "\U0001f1e6-\U0001f1ff" "]+"
)
_PUNCT = re.compile(r"[^\w\s가-힣-]", re.UNICODE)

_HANGUL = re.compile(r"[가-힣]")
_LATIN_TERM = re.compile(r"^[a-z0-9 .'-]+$")


def normalize(text: str) -> str:
    """Lowercase, strip HTML/URLs/emoji, collapse whitespace.

    Keeps hyphens (k-food) and Hangul; drops other punctuation so that
    "enak,banget!" still matches the term "enak".
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = _HTML.sub(" ", text)
    text = _URL.sub(" ", text)
    text = _EMOJI_ISH.sub(" ", text)
    text = text.lower()
    text = _PUNCT.sub(" ", text)
    return _WS.sub(" ", text).strip()


def contains_term(normalized_text: str, term: str) -> bool:
    """True if `term` appears in already-normalized text.

    Latin single/multi-word terms use boundary matching so "ada" does not fire
    inside "kepada". Korean terms fall back to substring matching, which is the
    correct behaviour for an agglutinative script.
    """
    term = term.lower().strip()
    if not term or not normalized_text:
        return False
    if _HANGUL.search(term):
        return term in normalized_text
    if _LATIN_TERM.match(term):
        pattern = r"(?<!\w)" + re.escape(term) + r"(?!\w)"
        return re.search(pattern, normalized_text) is not None
    return term in normalized_text


def matched_terms(normalized_text: str, terms: Iterable[str]) -> List[str]:
    """Every term from `terms` present in the text, longest first.

    Longest-first ordering means "tomat stevia" is reported instead of just
    "tomat" when both would match.
    """
    hits = [t for t in terms if contains_term(normalized_text, t)]
    hits.sort(key=len, reverse=True)
    return hits


def count_terms(normalized_text: str, terms: Iterable[str]) -> Tuple[int, List[str]]:
    hits = matched_terms(normalized_text, terms)
    return len(hits), hits


def tokenize(normalized_text: str) -> List[str]:
    return [tok for tok in normalized_text.split() if tok]


_STOPWORDS = {
    # Indonesian
    "yang", "dan", "di", "ke", "dari", "ini", "itu", "untuk", "dengan", "pada",
    "adalah", "aku", "saya", "kamu", "kita", "juga", "aja", "saja", "sih", "deh",
    "nya", "ya", "ga", "gak", "nggak", "tidak", "bisa", "ada", "udah", "sudah",
    "banget", "bgt", "kalo", "kalau", "gitu", "gini", "mau", "lagi", "tapi",
    "atau", "biar", "kan", "dong", "nih", "sama", "buat", "kok", "jadi", "punya",
    # English
    "the", "a", "an", "and", "or", "of", "to", "in", "is", "it", "this", "that",
    "for", "with", "on", "at", "be", "are", "was", "i", "you", "we", "my", "so",
    "but", "if", "have", "has", "just", "can", "do", "not", "very", "too",
}


def keywords(normalized_text: str, min_length: int = 3) -> List[str]:
    """Content words only - used for the per-segment 'top keywords' view."""
    return [
        tok
        for tok in tokenize(normalized_text)
        if len(tok) >= min_length and tok not in _STOPWORDS and not tok.isdigit()
    ]


def truncate(text: str, limit: int = 180) -> str:
    text = _WS.sub(" ", (text or "").strip())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"

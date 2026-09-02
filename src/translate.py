"""Free translation of sample quotes into Korean, no API key needed.

Zorvex's team reads Korean; most quotes are Indonesian (with English/Korean
mixed in). This translates the handful of sample quotes and evidence quotes
picked for the dashboard/report - never the full comment set.

Uses `deep-translator`'s free Google Translate backend (no account, no key,
no cost - just an outbound HTTPS call). If the package isn't installed, or a
call fails (no internet, rate limited), translation is skipped for those
quotes rather than failing the run.
"""

from __future__ import annotations

from typing import List, Optional, Sequence


def translation_available() -> bool:
    try:
        import deep_translator  # noqa: F401
    except ImportError:
        return False
    return True


def translate_to_korean(texts: Sequence[str]) -> List[Optional[str]]:
    """Best-effort translation, one call per quote. `None` per item on failure."""
    if not texts:
        return []
    try:
        from deep_translator import GoogleTranslator
    except ImportError:
        return [None] * len(texts)

    translator = GoogleTranslator(source="auto", target="ko")
    results: List[Optional[str]] = []
    for text in texts:
        if not text or not text.strip():
            results.append(None)
            continue
        try:
            results.append(translator.translate(text))
        except Exception:  # noqa: BLE001 - degrade, don't abort the run
            results.append(None)
    return results

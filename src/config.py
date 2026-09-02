"""Configuration loading: taxonomy, sentiment lexicon, and environment variables.

Deliberately dependency-free (stdlib only) so the baseline runs on a clean
Python 3.9+ install without `pip install` beyond `requests`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
CACHE_DIR = RAW_DIR / "cache"
OUTPUT_DIR = DATA_DIR / "output"
FIXTURE_DIR = DATA_DIR / "fixtures"


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_taxonomy(path: Path | None = None) -> Dict[str, Any]:
    """Keyword taxonomy: product terms, competitors, segments, topics, queries."""
    return _load_json(path or CONFIG_DIR / "taxonomy.json")


def load_sentiment_lexicon(path: Path | None = None) -> Dict[str, Any]:
    """Multilingual polarity lexicon used by the rules-based analyzer."""
    return _load_json(path or CONFIG_DIR / "sentiment_lexicon.json")


def load_sources_catalog(path: Path | None = None) -> Dict[str, Any]:
    """Source roadmap: cost, setup effort, and what each platform can return."""
    return _load_json(path or CONFIG_DIR / "sources.json")


def load_dotenv(path: Path | None = None) -> None:
    """Minimal .env reader so we don't depend on python-dotenv.

    Existing environment variables always win, so `set KEY=... && python run.py`
    overrides the file.
    """
    env_path = path or PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def get_api_key() -> str | None:
    """YouTube Data API v3 key, if one is configured."""
    load_dotenv()
    return os.environ.get("YOUTUBE_API_KEY") or None


def get_reddit_credentials() -> tuple[str | None, str | None]:
    """Reddit OAuth 'script' app credentials. See src/reddit_client.py for setup."""
    load_dotenv()
    return (
        os.environ.get("REDDIT_CLIENT_ID") or None,
        os.environ.get("REDDIT_CLIENT_SECRET") or None,
    )


def get_threads_token() -> str | None:
    """Threads user access token - requires a Meta app, not just a key."""
    load_dotenv()
    return os.environ.get("THREADS_ACCESS_TOKEN") or None


DEFAULT_GEMINI_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-3-flash",
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.7-flash",
]


def get_gemini_key() -> str | None:
    """Optional - only needed for the `--analyzer llm` upgrade path."""
    load_dotenv()
    return os.environ.get("GEMINI_API_KEY") or None


def get_gemini_models() -> list[str]:
    """Models to rotate through for `--analyzer llm`, batch by batch.

    Override with a comma-separated GEMINI_MODELS env var. Rotating spreads
    calls across each model's separate free-tier quota; llm_analyze.py falls
    back to the next model in the list if one fails, so an invalid/retired
    name here just gets skipped rather than breaking the run.
    """
    load_dotenv()
    raw = os.environ.get("GEMINI_MODELS")
    if raw:
        models = [m.strip() for m in raw.split(",") if m.strip()]
        if models:
            return models
    return list(DEFAULT_GEMINI_MODELS)


def get_run_password() -> str | None:
    """Optional shared password gating POST /api/run (starting an analysis).

    Unset by default so local dev / tests need nothing extra. Set RUN_PASSWORD
    once this is deployed somewhere public - the dashboard has no other login,
    so without this anyone who finds the URL can start runs and spend your
    YouTube/Gemini quota.
    """
    load_dotenv()
    return os.environ.get("RUN_PASSWORD") or None


def ensure_dirs() -> None:
    for directory in (RAW_DIR, CACHE_DIR, OUTPUT_DIR, FIXTURE_DIR):
        directory.mkdir(parents=True, exist_ok=True)

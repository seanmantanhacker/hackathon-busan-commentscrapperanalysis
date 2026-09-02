"""YouTube Data API v3 client.

Uses the public REST endpoints directly via `requests` rather than
`google-api-python-client`, to keep the install footprint at one dependency.

Why YouTube and not Instagram/TikTok
------------------------------------
Instagram's and TikTok's official APIs only return comments on accounts you
*own*. Reading competitor or category comments there requires scraping, which
is fragile and against their terms. The YouTube Data API exposes public
comments on *any* video with just an API key, which makes category-level
listening (the thing Zorvex actually needs) legitimately buildable.

Quota
-----
Default daily quota is 10,000 units.
  - search.list         = 100 units per call   <- the expensive one
  - commentThreads.list =   1 unit per call    (up to 100 comments per page)
  - videos.list         =   1 unit per call
So ~50 searches/day is the practical ceiling. Every response is cached to
`data/raw/cache/` so re-runs during development cost nothing.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests

from .comment import Comment
from .config import CACHE_DIR, FIXTURE_DIR

API_BASE = "https://www.googleapis.com/youtube/v3"

QUOTA_COST = {"search": 100, "commentThreads": 1, "videos": 1}


@dataclass
class Video:
    video_id: str
    title: str
    channel_title: str
    published_at: str
    description: str = ""
    source_query: str = ""


class QuotaExceeded(RuntimeError):
    """Raised when the API reports the daily quota is spent."""


class YouTubeClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        use_cache: bool = True,
        region_code: str = "ID",
        relevance_language: str = "id",
        request_delay: float = 0.0,
    ) -> None:
        self.api_key = api_key
        self.use_cache = use_cache
        self.region_code = region_code
        self.relevance_language = relevance_language
        self.request_delay = request_delay
        self.quota_used = 0
        self.calls_made = 0
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- caching

    def _cache_path(self, endpoint: str, params: Dict[str, Any]) -> Path:
        payload = json.dumps(
            {k: v for k, v in sorted(params.items()) if k != "key"},
            ensure_ascii=False,
        )
        digest = hashlib.sha1(f"{endpoint}:{payload}".encode("utf-8")).hexdigest()[:16]
        return CACHE_DIR / f"{endpoint}_{digest}.json"

    # ---------------------------------------------------------------- request

    def _get(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        cache_path = self._cache_path(endpoint, params)
        if self.use_cache and cache_path.exists():
            with cache_path.open("r", encoding="utf-8") as fh:
                return json.load(fh)

        if not self.api_key:
            raise RuntimeError(
                "No YOUTUBE_API_KEY configured. Set it in .env, "
                "or run with --source fixtures for the offline demo."
            )

        request_params = dict(params, key=self.api_key)
        response = requests.get(f"{API_BASE}/{endpoint}", params=request_params, timeout=30)
        self.calls_made += 1
        self.quota_used += QUOTA_COST.get(endpoint, 1)
        if self.request_delay:
            time.sleep(self.request_delay)

        if response.status_code == 403:
            detail = response.text[:400]
            if "quota" in detail.lower():
                raise QuotaExceeded(f"YouTube API quota exhausted: {detail}")
            raise RuntimeError(f"YouTube API returned 403 (check key/referrer restrictions): {detail}")
        response.raise_for_status()
        data = response.json()

        if self.use_cache:
            with cache_path.open("w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False)
        return data

    # ----------------------------------------------------------------- search

    def search_videos(
        self,
        query: str,
        *,
        max_results: int = 10,
        order: str = "relevance",
        published_after: Optional[str] = None,
    ) -> List[Video]:
        """search.list - 100 quota units per call. Returns at most 50 per page."""
        params: Dict[str, Any] = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": min(max_results, 50),
            "order": order,
            "regionCode": self.region_code,
            "relevanceLanguage": self.relevance_language,
        }
        if published_after:
            params["publishedAfter"] = published_after

        data = self._get("search", params)
        videos: List[Video] = []
        for item in data.get("items", []):
            video_id = item.get("id", {}).get("videoId")
            if not video_id:
                continue
            snippet = item.get("snippet", {})
            videos.append(
                Video(
                    video_id=video_id,
                    title=snippet.get("title", ""),
                    channel_title=snippet.get("channelTitle", ""),
                    published_at=snippet.get("publishedAt", ""),
                    description=snippet.get("description", ""),
                    source_query=query,
                )
            )
        return videos

    # --------------------------------------------------------------- comments

    def fetch_comments(
        self,
        video: Video,
        *,
        max_comments: int = 200,
        include_replies: bool = True,
    ) -> List[Comment]:
        """commentThreads.list - 1 quota unit per page of up to 100 threads.

        Videos with comments disabled return 403; that is expected and skipped
        rather than raising, because it is common and not an error in our flow.
        """
        collected: List[Comment] = []
        page_token: Optional[str] = None

        while len(collected) < max_comments:
            params: Dict[str, Any] = {
                "part": "snippet,replies" if include_replies else "snippet",
                "videoId": video.video_id,
                "maxResults": min(100, max_comments - len(collected)),
                "order": "relevance",
                "textFormat": "plainText",
            }
            if page_token:
                params["pageToken"] = page_token

            try:
                data = self._get("commentThreads", params)
            except QuotaExceeded:
                raise
            except RuntimeError as exc:
                # Comments disabled / video private - skip this video quietly.
                if "403" in str(exc):
                    break
                raise
            except requests.HTTPError as exc:  # pragma: no cover - network dependent
                status = exc.response.status_code if exc.response is not None else None
                if status in (403, 404):
                    break
                raise

            for thread in data.get("items", []):
                top = thread.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
                if not top:
                    continue
                collected.append(
                    Comment(
                        comment_id=thread.get("id", ""),
                        platform="youtube",
                        container_id=video.video_id,
                        container_title=video.title,
                        container_author=video.channel_title,
                        author=top.get("authorDisplayName", ""),
                        text=top.get("textDisplay", "") or top.get("textOriginal", ""),
                        like_count=int(top.get("likeCount", 0) or 0),
                        published_at=top.get("publishedAt", ""),
                        reply_count=int(thread.get("snippet", {}).get("totalReplyCount", 0) or 0),
                        source_query=video.source_query,
                        permalink=f"https://www.youtube.com/watch?v={video.video_id}&lc={thread.get('id', '')}",
                    )
                )
                if include_replies:
                    for reply in thread.get("replies", {}).get("comments", []):
                        rs = reply.get("snippet", {})
                        collected.append(
                            Comment(
                                comment_id=reply.get("id", ""),
                                platform="youtube",
                                container_id=video.video_id,
                                container_title=video.title,
                                container_author=video.channel_title,
                                author=rs.get("authorDisplayName", ""),
                                text=rs.get("textDisplay", "") or rs.get("textOriginal", ""),
                                like_count=int(rs.get("likeCount", 0) or 0),
                                published_at=rs.get("publishedAt", ""),
                                source_query=video.source_query,
                                permalink=f"https://www.youtube.com/watch?v={video.video_id}&lc={reply.get('id', '')}",
                            )
                        )

            page_token = data.get("nextPageToken")
            if not page_token:
                break

        return collected[:max_comments]

    # ------------------------------------------------------------------ stats

    def quota_report(self) -> Dict[str, Any]:
        return {
            "api_calls": self.calls_made,
            "quota_units_used": self.quota_used,
            "daily_quota_default": 10000,
            "remaining_estimate": max(0, 10000 - self.quota_used),
        }


# ---------------------------------------------------------------- fixtures


def load_fixture_comments(path: Optional[Path] = None) -> List[Comment]:
    """Offline sample set so the pipeline is demoable without an API key."""
    fixture_path = path or FIXTURE_DIR / "sample_comments.json"
    with fixture_path.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)
    return [Comment.from_dict(row) for row in raw]

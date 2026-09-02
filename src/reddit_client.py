"""Reddit source — official OAuth API (oauth.reddit.com).

Why OAuth and not the old `.json` trick
---------------------------------------
Unauthenticated `www.reddit.com/*.json` requests now return 403, and
`old.reddit.com/*.json` answers 200 but redirects to a login page — verified
2026-09. Anonymous read access is closed. The supported path is an OAuth
"script" app, which is free and takes about two minutes to create:

  1. https://www.reddit.com/prefs/apps  ->  "create another app..."
  2. Choose type **script**; redirect URI can be http://localhost:8080
  3. Copy the client id (under the app name) and the secret
  4. Put both in .env as REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET

Rate limits: 100 queries per minute per OAuth client, averaged over 10 minutes.
Reddit publishes the remaining budget in x-ratelimit-* response headers, which
this client reads and respects.

Reddit's terms require a descriptive User-Agent identifying the app; sending a
browser-spoofing UA is both against the rules and a good way to get blocked.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence

import requests

from .comment import Comment
from .config import CACHE_DIR

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API_BASE = "https://oauth.reddit.com"
USER_AGENT = "python:sns-listening:0.1 (by /u/{username}; hackathon market research)"

# Subreddits worth listening to for a premium/healthy food product. Indonesian
# communities first, then the global health/diet ones that discuss the category
# even when they never mention Indonesia.
DEFAULT_SUBREDDITS = (
    "indonesia", "indonesian", "IndonesiaFood", "finansial",
    "nutrition", "HealthyFood", "EatCheapAndHealthy", "loseit",
    "keto", "diabetes", "gardening", "tomatoes", "Cooking", "food",
)


@dataclass
class RedditPost:
    post_id: str
    title: str
    subreddit: str
    permalink: str
    score: int
    num_comments: int
    created_utc: float
    selftext: str = ""
    source_query: str = ""


class RedditAuthError(RuntimeError):
    """Credentials missing or rejected."""


class RedditClient:
    def __init__(
        self,
        client_id: Optional[str],
        client_secret: Optional[str],
        *,
        username: str = "unknown",
        use_cache: bool = True,
        min_interval: float = 0.65,   # ~92 req/min, just under the 100 QPM cap
    ) -> None:
        if not client_id or not client_secret:
            raise RedditAuthError(
                "REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET not set. Create a free "
                "'script' app at https://www.reddit.com/prefs/apps and add both to "
                ".env — see src/reddit_client.py for the steps."
            )
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_agent = USER_AGENT.format(username=username)
        self.use_cache = use_cache
        self.min_interval = min_interval

        self._token: Optional[str] = None
        self._token_expires_at = 0.0
        self._last_request = 0.0
        self.requests_made = 0
        self.rate_remaining: Optional[float] = None

        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ auth

    def _access_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token

        response = requests.post(
            TOKEN_URL,
            data={"grant_type": "client_credentials"},
            auth=(self.client_id, self.client_secret),
            headers={"User-Agent": self.user_agent},
            timeout=30,
        )
        if response.status_code == 401:
            raise RedditAuthError(
                "Reddit rejected the credentials (401). Check the client id is the "
                "short string under the app name, not the app name itself."
            )
        response.raise_for_status()
        payload = response.json()
        self._token = payload["access_token"]
        self._token_expires_at = time.time() + float(payload.get("expires_in", 3600))
        return self._token

    # --------------------------------------------------------------- request

    def _get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        elapsed = time.time() - self._last_request
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)

        response = requests.get(
            f"{API_BASE}{path}",
            params=params,
            headers={
                "Authorization": f"Bearer {self._access_token()}",
                "User-Agent": self.user_agent,
            },
            timeout=30,
        )
        self._last_request = time.time()
        self.requests_made += 1

        remaining = response.headers.get("x-ratelimit-remaining")
        if remaining is not None:
            try:
                self.rate_remaining = float(remaining)
            except ValueError:
                pass

        if response.status_code == 429:
            reset = float(response.headers.get("x-ratelimit-reset", 60))
            time.sleep(min(reset, 60) + 1)
            return self._get(path, params)
        response.raise_for_status()
        return response.json()

    # ---------------------------------------------------------------- search

    def search(
        self,
        query: str,
        *,
        limit: int = 25,
        subreddits: Optional[Sequence[str]] = None,
        sort: str = "relevance",
        time_filter: str = "year",
    ) -> List[RedditPost]:
        """Search posts, either site-wide or restricted to given subreddits."""
        if subreddits:
            path = f"/r/{'+'.join(subreddits)}/search"
            params: Dict[str, Any] = {"restrict_sr": "true"}
        else:
            path = "/search"
            params = {}
        params.update({"q": query, "limit": min(limit, 100), "sort": sort, "t": time_filter, "type": "link"})

        data = self._get(path, params)
        posts: List[RedditPost] = []
        for child in data.get("data", {}).get("children", []):
            if child.get("kind") != "t3":
                continue
            d = child["data"]
            posts.append(
                RedditPost(
                    post_id=d.get("id", ""),
                    title=d.get("title", ""),
                    subreddit=f"r/{d.get('subreddit', '')}",
                    permalink="https://www.reddit.com" + d.get("permalink", ""),
                    score=int(d.get("score", 0) or 0),
                    num_comments=int(d.get("num_comments", 0) or 0),
                    created_utc=float(d.get("created_utc", 0) or 0),
                    selftext=d.get("selftext", "") or "",
                    source_query=query,
                )
            )
        return posts

    # -------------------------------------------------------------- comments

    def fetch_comments(self, post: RedditPost, *, max_comments: int = 200, depth: int = 3) -> List[Comment]:
        """Comments on one post, flattened across nesting levels."""
        try:
            data = self._get(
                f"/comments/{post.post_id}",
                {"limit": min(max_comments, 500), "depth": depth, "sort": "top"},
            )
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status in (403, 404):     # removed, quarantined, or private
                return []
            raise

        # The comments endpoint returns [post_listing, comment_listing].
        listing = data[1] if isinstance(data, list) and len(data) > 1 else {}
        collected: List[Comment] = []
        self._walk(listing, post, collected, max_comments)
        return collected[:max_comments]

    def _walk(self, listing: Dict[str, Any], post: RedditPost, out: List[Comment], limit: int) -> None:
        for child in listing.get("data", {}).get("children", []):
            if len(out) >= limit:
                return
            if child.get("kind") != "t1":       # skip "more comments" stubs
                continue
            d = child.get("data", {})
            body = d.get("body", "") or ""
            if body in ("[deleted]", "[removed]", ""):
                continue

            out.append(
                Comment(
                    comment_id=f"reddit_{d.get('id', '')}",
                    platform="reddit",
                    container_id=post.post_id,
                    container_title=post.title,
                    container_author=post.subreddit,
                    author=d.get("author", "") or "",
                    text=body,
                    like_count=int(d.get("score", 0) or 0),
                    published_at=_iso(d.get("created_utc")),
                    reply_count=0,
                    source_query=post.source_query,
                    permalink="https://www.reddit.com" + (d.get("permalink", "") or ""),
                )
            )

            replies = d.get("replies")
            if isinstance(replies, dict):
                self._walk(replies, post, out, limit)

    # ------------------------------------------------------------------ misc

    def usage_report(self) -> Dict[str, Any]:
        return {
            "requests": self.requests_made,
            "rate_limit_remaining": self.rate_remaining,
            "limit_note": "100 queries/minute per OAuth client",
        }


def _iso(created_utc: Any) -> str:
    from datetime import datetime, timezone

    try:
        return datetime.fromtimestamp(float(created_utc), tz=timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return ""


def collect(
    client: RedditClient,
    queries: Sequence[str],
    *,
    posts_per_query: int = 10,
    comments_per_post: int = 100,
    subreddits: Optional[Sequence[str]] = None,
    log=lambda message: None,
) -> tuple[List[Comment], Dict[str, Any]]:
    """Run a full Reddit collection pass. Mirrors the YouTube fetch loop."""
    comments: List[Comment] = []
    seen_posts: set[str] = set()
    seen_ids: set[str] = set()

    for query in queries:
        try:
            posts = client.search(query, limit=posts_per_query, subreddits=subreddits)
        except Exception as exc:  # noqa: BLE001 - one bad query shouldn't end the run
            log(f"  ! reddit search failed for '{query}': {exc}")
            continue

        log(f"  - reddit '{query}' -> {len(posts)} posts")
        for post in posts:
            if post.post_id in seen_posts or post.num_comments == 0:
                continue
            seen_posts.add(post.post_id)
            try:
                fetched = client.fetch_comments(post, max_comments=comments_per_post)
            except Exception as exc:  # noqa: BLE001
                log(f"    ! reddit comments failed for {post.post_id}: {exc}")
                continue
            for comment in fetched:
                if comment.comment_id not in seen_ids:
                    seen_ids.add(comment.comment_id)
                    comments.append(comment)

    return comments, {"posts": len(seen_posts), "usage": client.usage_report()}

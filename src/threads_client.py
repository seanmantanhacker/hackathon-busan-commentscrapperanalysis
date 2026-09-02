"""Threads (Meta) source — best-effort, and the weakest of the three.

READ THIS BEFORE RELYING ON IT
------------------------------
Threads is not equivalent to YouTube or Reddit for this use case, for reasons
that are structural rather than fixable:

1. **You cannot read replies to other people's posts.** The Threads API exposes
   replies only for posts on an account you own (`threads_manage_replies` /
   `threads_read_replies`). The rich comment discussions this whole tool is
   built to mine are, for third-party posts, simply not reachable.

2. **Keyword search returns top-level posts only**, via the `keyword_search`
   endpoint, and requires the `threads_keyword_search` permission. So Threads
   contributes posts *mentioning* your keywords, not conversation *about* them.

3. **It needs a user OAuth token, not an API key.** Unlike YouTube (paste a key)
   or Reddit (two-minute script app), this requires a Meta app, a linked Threads
   account, an OAuth redirect flow, and app review before it works for anyone
   but yourself.

4. **This module is unverified against the live API.** It was written to Meta's
   documented contract but could not be exercised here without a token. Treat a
   successful run as the first test, and check `docs` if the shape has drifted:
   https://developers.facebook.com/docs/threads

For Zorvex's own Instagram/Threads account, the officially supported path is the
Instagram Graph API on their own media — a different (and easy) integration that
does not need any of the above. That is the right way to cover their own
channel; this module is only for category-level keyword listening.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

import requests

from .comment import Comment

API_BASE = "https://graph.threads.net/v1.0"

POST_FIELDS = "id,text,username,permalink,timestamp,like_count,replies_count,is_quote_post"


class ThreadsUnavailable(RuntimeError):
    """No token configured, or the API refused the request."""


class ThreadsClient:
    def __init__(self, access_token: Optional[str], *, timeout: int = 30) -> None:
        if not access_token:
            raise ThreadsUnavailable(
                "THREADS_ACCESS_TOKEN not set. Threads needs a Meta app plus a user "
                "OAuth token (see the notes at the top of src/threads_client.py) — "
                "it is not a paste-in API key like YouTube."
            )
        self.access_token = access_token
        self.timeout = timeout
        self.requests_made = 0

    def _get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        params = dict(params, access_token=self.access_token)
        response = requests.get(f"{API_BASE}{path}", params=params, timeout=self.timeout)
        self.requests_made += 1

        if response.status_code in (400, 401, 403):
            detail = ""
            try:
                detail = response.json().get("error", {}).get("message", "")
            except ValueError:
                detail = response.text[:200]
            raise ThreadsUnavailable(
                f"Threads API returned {response.status_code}: {detail}. "
                "The most common cause is that the token lacks the "
                "'threads_keyword_search' permission, which needs app review."
            )
        response.raise_for_status()
        return response.json()

    def keyword_search(self, query: str, *, limit: int = 25, search_type: str = "TOP") -> List[Comment]:
        """Public posts matching a keyword.

        Note these are *posts*, not replies — see limitation 2 in the module
        docstring. They are mapped onto `Comment` so the rest of the pipeline
        can treat them uniformly.
        """
        data = self._get(
            "/keyword_search",
            {"q": query, "search_type": search_type, "fields": POST_FIELDS, "limit": min(limit, 100)},
        )

        posts: List[Comment] = []
        for item in data.get("data", []):
            text = item.get("text") or ""
            if not text.strip():
                continue
            posts.append(
                Comment(
                    comment_id=f"threads_{item.get('id', '')}",
                    platform="threads",
                    container_id=item.get("id", ""),
                    container_title=f"Threads post by @{item.get('username', 'unknown')}",
                    container_author=f"@{item.get('username', 'unknown')}",
                    author=item.get("username", "") or "",
                    text=text,
                    like_count=int(item.get("like_count", 0) or 0),
                    published_at=item.get("timestamp", "") or "",
                    reply_count=int(item.get("replies_count", 0) or 0),
                    source_query=query,
                    permalink=item.get("permalink", "") or "",
                )
            )
        return posts

    def own_post_replies(self, thread_id: str, *, limit: int = 100) -> List[Comment]:
        """Replies to a post on the authenticated account — the one reply source
        Threads actually permits. Useful once Zorvex posts from their own account."""
        data = self._get(
            f"/{thread_id}/replies",
            {"fields": POST_FIELDS, "limit": min(limit, 100)},
        )
        replies: List[Comment] = []
        for item in data.get("data", []):
            text = item.get("text") or ""
            if not text.strip():
                continue
            replies.append(
                Comment(
                    comment_id=f"threads_{item.get('id', '')}",
                    platform="threads",
                    container_id=thread_id,
                    container_title="Reply to own Threads post",
                    container_author=f"@{item.get('username', 'unknown')}",
                    author=item.get("username", "") or "",
                    text=text,
                    like_count=int(item.get("like_count", 0) or 0),
                    published_at=item.get("timestamp", "") or "",
                    source_query="own_account",
                    permalink=item.get("permalink", "") or "",
                )
            )
        return replies

    def usage_report(self) -> Dict[str, Any]:
        return {"requests": self.requests_made}


def collect(
    client: ThreadsClient,
    queries: Sequence[str],
    *,
    posts_per_query: int = 25,
    log=lambda message: None,
) -> tuple[List[Comment], Dict[str, Any]]:
    comments: List[Comment] = []
    seen: set[str] = set()

    for query in queries:
        try:
            posts = client.keyword_search(query, limit=posts_per_query)
        except ThreadsUnavailable as exc:
            log(f"  ! threads search failed for '{query}': {exc}")
            continue
        except Exception as exc:  # noqa: BLE001
            log(f"  ! threads search errored for '{query}': {exc}")
            continue

        log(f"  - threads '{query}' -> {len(posts)} posts")
        for post in posts:
            if post.comment_id not in seen:
                seen.add(post.comment_id)
                comments.append(post)

    return comments, {"usage": client.usage_report()}

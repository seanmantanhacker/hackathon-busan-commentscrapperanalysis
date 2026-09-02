"""The platform-neutral comment record every source produces.

The pipeline downstream of fetching knows nothing about YouTube, Reddit, or
Threads — it only sees `Comment`. Adding a platform therefore means writing a
fetcher that emits these, and nothing else changes.

Field mapping per platform:

  field              youtube            reddit                 threads
  -----------------  -----------------  ---------------------  --------------------
  container_id       video id           post id (t3_…)         root post id
  container_title    video title        post title             root post text
  container_author   channel name       r/subreddit            account username
  like_count         likes              upvote score           likes
  permalink          watch?v=…&lc=…     reddit.com/r/…         threads.net/…
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any, Dict

PLATFORMS = ("youtube", "reddit", "threads")

# Field names before the tool became multi-platform. Kept so previously saved
# raw dumps in data/raw/ still load.
_LEGACY_KEYS = {
    "video_id": "container_id",
    "video_title": "container_title",
    "channel_title": "container_author",
}


@dataclass
class Comment:
    comment_id: str
    text: str
    platform: str = "youtube"
    container_id: str = ""
    container_title: str = ""
    container_author: str = ""
    author: str = ""
    like_count: int = 0
    published_at: str = ""
    reply_count: int = 0
    source_query: str = ""
    permalink: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, row: Dict[str, Any]) -> "Comment":
        """Build from a dict, tolerating legacy YouTube-shaped keys and extras."""
        known = {f.name for f in fields(cls)}
        data: Dict[str, Any] = {}
        for key, value in row.items():
            key = _LEGACY_KEYS.get(key, key)
            if key in known:
                data[key] = value
        data.setdefault("platform", "youtube")
        data.setdefault("comment_id", "")
        data.setdefault("text", "")
        return cls(**data)

    # -- read-only aliases, so older call sites keep working -----------------

    @property
    def video_id(self) -> str:
        return self.container_id

    @property
    def video_title(self) -> str:
        return self.container_title

    @property
    def channel_title(self) -> str:
        return self.container_author

#!/usr/bin/env python3
"""Verify Reddit credentials before spending a real run on them.

    python check_reddit.py

Checks, in order: credentials present -> OAuth token issued -> a search returns
posts -> comments are readable. Each step prints why it failed, if it did.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.config import get_reddit_credentials  # noqa: E402
from src.reddit_client import (  # noqa: E402
    DEFAULT_SUBREDDITS,
    RedditAuthError,
    RedditClient,
)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    print("=" * 62)
    print("  Reddit credential check")
    print("=" * 62)

    client_id, client_secret = get_reddit_credentials()
    print(f"  REDDIT_CLIENT_ID     : {'set (' + client_id[:4] + '…)' if client_id else 'MISSING'}")
    print(f"  REDDIT_CLIENT_SECRET : {'set' if client_secret else 'MISSING'}")

    if not (client_id and client_secret):
        print()
        print("  Add both to .env, then re-run this script.")
        print("  Create a free 'script' app at https://www.reddit.com/prefs/apps")
        return 2

    try:
        client = RedditClient(client_id, client_secret)
    except RedditAuthError as exc:
        print(f"\n  FAILED: {exc}")
        return 1

    print("\n  [1/3] Requesting OAuth token…")
    try:
        token = client._access_token()
        print(f"        OK — token issued ({len(token)} chars)")
    except RedditAuthError as exc:
        print(f"        FAILED: {exc}")
        print("\n  Most common cause: the client id is the short string UNDER the")
        print("  app name in prefs/apps, not the app's display name.")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"        FAILED: {type(exc).__name__}: {exc}")
        return 1

    print("\n  [2/3] Searching for 'stevia tomato'…")
    try:
        posts = client.search("stevia tomato", limit=5)
    except Exception as exc:  # noqa: BLE001
        print(f"        FAILED: {type(exc).__name__}: {exc}")
        return 1

    print(f"        OK — {len(posts)} posts (site-wide)")
    for post in posts[:5]:
        print(f"          {post.subreddit:<20} [{post.num_comments:>3}c {post.score:>4}p] {post.title[:48]}")

    print("\n  [3/3] Fetching comments from the busiest post…")
    with_comments = [p for p in posts if p.num_comments > 0]
    if not with_comments:
        print("        (no post had comments — try a different query)")
    else:
        target = max(with_comments, key=lambda p: p.num_comments)
        try:
            comments = client.fetch_comments(target, max_comments=10)
        except Exception as exc:  # noqa: BLE001
            print(f"        FAILED: {type(exc).__name__}: {exc}")
            return 1
        print(f"        OK — {len(comments)} comments from {target.subreddit}")
        for comment in comments[:4]:
            print(f"          [{comment.like_count:>4}] {comment.text[:60].replace(chr(10), ' ')}")

    usage = client.usage_report()
    print()
    print("=" * 62)
    print(f"  READY — {usage['requests']} requests used, "
          f"{usage['rate_limit_remaining']} remaining in this window")
    print(f"  Default subreddits: {', '.join(DEFAULT_SUBREDDITS[:6])}, …")
    print()
    print("  Now run:  python run.py --source youtube reddit --tag combined")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

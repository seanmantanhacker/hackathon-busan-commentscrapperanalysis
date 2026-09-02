"""Smoke + behaviour tests. Run with: python tests/test_pipeline.py

Kept dependency-free (no pytest required) so it runs anywhere the pipeline runs.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.analyze import RulesAnalyzer
from src.config import load_sentiment_lexicon, load_taxonomy
from src.pipeline import Pipeline, PipelineConfig
from src.relevance import RelevanceScorer
from src.textutil import contains_term, normalize
from src.comment import Comment
from src.youtube_client import load_fixture_comments

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}" + (f" — {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


def test_normalize() -> None:
    print("\ntextutil")
    check("strips html/urls/emoji", normalize("<b>Enak</b> banget! https://x.co 😋") == "enak banget")
    check("keeps hyphen for k-food", "k-food" in normalize("Suka K-Food banget"))
    check("keeps hangul", "맛있" in normalize("정말 맛있어요"))
    check("word boundary: 'ada' not in 'kepada'", not contains_term(normalize("kepada semua"), "ada"))
    check("multi-word term matches", contains_term(normalize("beli tomat stevia kemarin"), "tomat stevia"))
    check("korean substring matches", contains_term(normalize("스테비아 토마토 좋아요"), "스테비아 토마토"))


def test_relevance() -> None:
    print("\nrelevance")
    scorer = RelevanceScorer(load_taxonomy())

    core = scorer.score("Tomat stevia ini manis banget enak")
    check("product mention -> product_core", core.bucket == "product_core", core.bucket)

    spam = scorer.score("ikutan giveaway ya kak semoga menang hadiahnya")
    check("giveaway flagged as spam", spam.is_spam)
    check("spam is not relevant", not spam.is_relevant)

    off = scorer.score("Lagu backsoundnya apa ya kak enak banget didenger")
    check("off-topic rejected", not off.is_relevant, off.bucket)

    short = scorer.score("mantap")
    check("too-short rejected", not short.is_relevant)

    comp = scorer.score("Shine muscat dan buah import premium emang juara")
    check("competitor mention -> competitor", comp.bucket == "competitor", comp.bucket)


def test_sentiment() -> None:
    print("\nsentiment")
    analyzer = RulesAnalyzer(load_taxonomy(), load_sentiment_lexicon())

    pos, pos_label = analyzer.sentiment(normalize("Enak banget, recommended, ketagihan"))
    check("positive detected", pos_label == "positive", f"{pos} {pos_label}")

    neg, neg_label = analyzer.sentiment(normalize("Kemahalan banget, kecewa, gak worth"))
    check("negative detected", neg_label == "negative", f"{neg} {neg_label}")

    negated, negated_label = analyzer.sentiment(normalize("gak enak sama sekali"))
    check("negation flips polarity", negated < 0, f"{negated} {negated_label}")

    korean, korean_label = analyzer.sentiment(normalize("정말 맛있어요 최고"))
    check("korean positive detected", korean_label == "positive", f"{korean} {korean_label}")


def test_intent_and_segments() -> None:
    print("\nintent + segments")
    taxonomy = load_taxonomy()
    analyzer = RulesAnalyzer(taxonomy, load_sentiment_lexicon())

    check("repeat intent", analyzer.intent(normalize("udah langganan, beli lagi tiap minggu")) == "repeat")
    check("buy intent", analyzer.intent(normalize("mau beli ah besok")) == "intent")
    check("curious intent", analyzer.intent(normalize("beli dimana ya kak")) == "curious")
    check("no intent", analyzer.intent(normalize("tomatnya kelihatan segar sekali")) == "none")

    seg, _ = analyzer.segment(normalize("aku lagi diet defisit kalori cari rendah gula"), ["health"])
    check("diet -> health_diet_seeker", seg == "health_diet_seeker", seg)

    seg2, _ = analyzer.segment(normalize("suka makanan korea dan k-food"), [])
    check("k-food -> kfood_enthusiast", seg2 == "kfood_enthusiast", seg2)

    seg3, _ = analyzer.segment(normalize("kemahalan banget gak worth mending yang murah"), ["price"])
    check("price complaint -> price_sensitive", seg3 == "price_sensitive", seg3)


def test_lead_grading() -> None:
    print("\nlead grading (Q&A A4 rubric)")
    analyzer = RulesAnalyzer(load_taxonomy(), load_sentiment_lexicon())

    strong, strong_grade = analyzer.lead_score(
        segment="health_diet_seeker", sentiment_score=0.7, intent="repeat",
        topics=["taste", "health", "availability"], relevance_bucket="product_core", like_count=200,
    )
    check("strong lead grades A", strong_grade == "A", f"{strong} {strong_grade}")

    weak, weak_grade = analyzer.lead_score(
        segment="price_sensitive", sentiment_score=-0.5, intent="none",
        topics=["price"], relevance_bucket="category", like_count=0,
    )
    check("price-sensitive grades D", weak_grade == "D", f"{weak} {weak_grade}")
    check("strong outranks weak", strong > weak)


def test_fixtures() -> None:
    print("\nfixtures")
    comments = load_fixture_comments()
    check("fixtures load", len(comments) >= 50, str(len(comments)))
    check("all are Comment objects", all(isinstance(c, Comment) for c in comments))
    check("ids are unique", len({c.comment_id for c in comments}) == len(comments))


def test_end_to_end() -> None:
    print("\nend-to-end")
    with tempfile.TemporaryDirectory() as tmp:
        config = PipelineConfig(sources=["fixtures"], output_dir=Path(tmp), verbose=False)
        result = Pipeline(config).run(tag="test")

        stats = result["stats"]
        check("comments analyzed", stats["analyzed_comments"] > 20, str(stats["analyzed_comments"]))
        check("segments formed", len(result["profiles"]) >= 4, str(len(result["profiles"])))
        check("recommendations produced", len(result["recommendations"]) == len(result["profiles"]))
        check("strategic notes produced", len(result["notes"]) > 0)
        check("noise was filtered", result["filter_summary"]["dropped_off_topic"] > 0)

        for key in ("markdown", "json", "csv", "latest"):
            check(f"{key} output written", result["paths"][key].exists())

        report = result["paths"]["markdown"].read_text(encoding="utf-8")
        check("report has segments section", "## 3 · Customer segments" in report)
        check("report has recommendations", "## 4 · Marketing recommendations" in report)

        priorities = [r.priority for r in result["recommendations"]]
        check("priorities are 1..n in order", priorities == sorted(priorities))

        price_rec = next((r for r in result["recommendations"] if r.segment_id == "price_sensitive"), None)
        if price_rec:
            check(
                "price-sensitive ranked low (A4 says low-quality lead)",
                price_rec.priority > len(result["recommendations"]) // 2,
                f"priority {price_rec.priority}",
            )


def test_permalinks() -> None:
    print("\nsource links")
    from src.youtube_client import Video, YouTubeClient

    client = YouTubeClient("fake-key", use_cache=False)
    video = Video(video_id="abc123", title="T", channel_title="C", published_at="")
    # Build one comment through the real parser via a minimal API payload.
    payload = {"items": [{"id": "CmtId", "snippet": {
        "topLevelComment": {"snippet": {
            "authorDisplayName": "u", "textDisplay": "tomat stevia enak banget",
            "likeCount": 5, "publishedAt": "2026-01-01T00:00:00Z"}},
        "totalReplyCount": 0}}]}
    client._get = lambda endpoint, params: payload  # type: ignore[assignment]
    comments = client.fetch_comments(video, max_comments=1)

    check("comment carries a permalink", bool(comments and comments[0].permalink))
    check("permalink points at the video", "watch?v=abc123" in comments[0].permalink)
    check("permalink deep-links the comment", "lc=CmtId" in comments[0].permalink)

    with tempfile.TemporaryDirectory() as tmp:
        config = PipelineConfig(sources=["fixtures"], output_dir=Path(tmp), verbose=False)
        result = Pipeline(config).run(tag="links")
        quotes = [q for p in result["profiles"] for q in p.sample_quotes]
        check("quotes expose a permalink field", all("permalink" in q for q in quotes))
        check("quotes expose their source title", all("source" in q for q in quotes))
        recs = result["recommendations"]
        check("recommendations expose evidence_permalink",
              all(hasattr(r, "evidence_permalink") for r in recs))


def test_pdf_export() -> None:
    print("\npdf export")
    from src.pdf_export import export_pdf, find_browser, markdown_to_html

    sample = (
        "# Title\n\nIntro **bold** and `code`.\n\n"
        "## Section\n\n| A | B |\n|---|---:|\n| 1 | 2 |\n\n"
        "> A quote\n\n- item one\n- item two\n\n---\n"
    )
    html = markdown_to_html(sample, title="T")
    check("html has doctype", html.startswith("<!DOCTYPE html>"))
    check("heading converted", "<h1>Title</h1>" in html)
    check("bold converted", "<strong>bold</strong>" in html)
    check("code converted", "<code>code</code>" in html)
    check("table converted", "<table" in html and "<th" in html and "<td" in html)
    check("right align honoured", 'text-align:right' in html)
    check("blockquote converted", "<blockquote>" in html)
    check("list converted", "<ul>" in html and html.count("<li>") == 2)
    check("rule converted", "<hr/>" in html)

    headless_table = markdown_to_html("| | |\n|---|---|\n| k | v |\n")
    check("empty-header table marked headless", 'class="headless"' in headless_table)

    korean = markdown_to_html("# 건강·다이어트 관심층\n")
    check("korean preserved", "건강·다이어트 관심층" in korean)
    check("br tag preserved", "<br/>" in markdown_to_html("- a <br/> b\n"))
    check("stray html escaped", "&lt;script&gt;" in markdown_to_html("- <script>x</script>\n"))

    with tempfile.TemporaryDirectory() as tmp:
        md = Path(tmp) / "report_test.md"
        md.write_text(sample, encoding="utf-8")
        result = export_pdf(md)
        check("html always written", result["html"] is not None and result["html"].exists())
        if find_browser():
            check("pdf written", result["pdf"] is not None and result["pdf"].exists())
            check("pdf is non-trivial", result["pdf"].stat().st_size > 1000)
        else:
            print("  [SKIP] pdf render — no Edge/Chrome on this machine")


def test_web_server() -> None:
    print("\nweb dashboard")
    import socket
    import threading
    import time
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer

    from web.server import Handler, STATIC_DIR

    for name in ("index.html", "styles.css", "app.js"):
        check(f"static/{name} present", (STATIC_DIR / name).exists())

    with socket.socket() as probe:          # let the OS pick a free port
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.2)
    base = f"http://127.0.0.1:{port}"

    def get(path: str) -> tuple[int, bytes]:
        try:
            with urllib.request.urlopen(base + path, timeout=5) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    try:
        status, body = get("/")
        check("GET / serves the page", status == 200 and b"<title>" in body)
        check("GET /static/styles.css", get("/static/styles.css")[0] == 200)
        check("GET /static/app.js", get("/static/app.js")[0] == 200)

        status, body = get("/api/config")
        config = json.loads(body)
        check("GET /api/config", status == 200 and "has_youtube_key" in config)

        status, body = get("/api/progress")
        check("GET /api/progress", status == 200 and "state" in json.loads(body))

        status, body = get("/api/reports")
        check("GET /api/reports", status == 200 and "reports" in json.loads(body))

        check("unknown route 404s", get("/api/nope")[0] == 404)
        # The download route must not escape data/output.
        check("path traversal blocked", get("/api/download/../../.env")[0] in (403, 404))
        check("non-downloadable ext blocked", get("/api/download/taxonomy.py")[0] in (403, 404))
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_comment_model() -> None:
    print("\nplatform-neutral comment model")
    from src.comment import Comment

    legacy = Comment.from_dict({
        "comment_id": "x1", "text": "enak", "video_id": "v1",
        "video_title": "T", "channel_title": "C", "like_count": 3,
    })
    check("legacy keys migrate", legacy.container_id == "v1" and legacy.container_author == "C")
    check("platform defaults to youtube", legacy.platform == "youtube")
    check("alias properties still read", legacy.video_title == "T")
    check("unknown keys ignored", Comment.from_dict({"comment_id": "a", "text": "b", "junk": 1}).text == "b")


def test_reddit_client() -> None:
    print("\nreddit source")
    from src.reddit_client import DEFAULT_SUBREDDITS, RedditAuthError, RedditClient

    try:
        RedditClient(None, None)
        check("missing credentials raise", False, "no exception")
    except RedditAuthError as exc:
        check("missing credentials raise", True)
        check("error explains the fix", "prefs/apps" in str(exc))

    client = RedditClient("id", "secret")
    check("user-agent is descriptive, not spoofed",
          "sns-listening" in client.user_agent and "Mozilla" not in client.user_agent)
    check("rate limiting is on by default", client.min_interval > 0)
    check("default subreddits include indonesia", "indonesia" in DEFAULT_SUBREDDITS)

    # Parse a realistic listing payload without touching the network.
    payload = {"data": {"children": [
        {"kind": "t1", "data": {"id": "c1", "body": "Stevia tomatoes are great", "score": 12,
                                "author": "u1", "created_utc": 1750000000, "permalink": "/r/x/c1",
                                "replies": {"data": {"children": [
                                    {"kind": "t1", "data": {"id": "c2", "body": "agreed, very sweet",
                                                            "score": 4, "author": "u2",
                                                            "created_utc": 1750000100, "permalink": "/r/x/c2"}},
                                ]}}}},
        {"kind": "t1", "data": {"id": "c3", "body": "[deleted]", "score": 0, "author": "u3"}},
        {"kind": "more", "data": {"id": "m1"}},
    ]}}

    from src.reddit_client import RedditPost

    post = RedditPost(post_id="p1", title="Sweet tomatoes?", subreddit="r/nutrition",
                      permalink="https://reddit.com/r/nutrition/p1", score=50,
                      num_comments=3, created_utc=1750000000, source_query="stevia tomato")
    out: list = []
    client._walk(payload, post, out, 100)
    check("nested replies flattened", len(out) == 2, f"got {len(out)}")
    check("deleted comments dropped", all("[deleted]" not in c.text for c in out))
    check("'more' stubs skipped", all(c.comment_id != "reddit_m1" for c in out))
    check("platform tagged reddit", all(c.platform == "reddit" for c in out))
    check("subreddit becomes container_author", out[0].container_author == "r/nutrition")
    check("score maps to like_count", out[0].like_count == 12)
    check("timestamp converted to iso", out[0].published_at.startswith("20"))


def test_threads_client() -> None:
    print("\nthreads source")
    from src.threads_client import ThreadsClient, ThreadsUnavailable

    try:
        ThreadsClient(None)
        check("missing token raises", False, "no exception")
    except ThreadsUnavailable as exc:
        check("missing token raises", True)
        check("error explains it is not a plain key", "not a paste-in API key" in str(exc))


def test_multi_source_pipeline() -> None:
    print("\nmulti-source")
    import tempfile as _tf
    from src.pipeline import Pipeline, PipelineConfig

    with _tf.TemporaryDirectory() as tmp:
        # Sources without credentials must be skipped, not fatal.
        config = PipelineConfig(
            sources=["fixtures", "reddit", "threads"], output_dir=Path(tmp), verbose=False,
        )
        result = Pipeline(config).run(tag="multi")
        check("run survives unconfigured sources", result["stats"]["analyzed_comments"] > 20)
        check("sources recorded in metadata", result["run_meta"]["sources"] == ["fixtures", "reddit", "threads"])
        per_source = result["run_meta"].get("per_source", {})
        check("reddit reported as skipped", per_source.get("reddit", {}).get("comments") == 0)
        check("threads reported as skipped", per_source.get("threads", {}).get("comments") == 0)
        check("platform mix present", "platform_mix" in result["stats"])

        unknown = PipelineConfig(sources=["fixtures", "myspace"], output_dir=Path(tmp), verbose=False)
        result2 = Pipeline(unknown).run(tag="unknown")
        check("unknown source ignored, run continues", result2["stats"]["analyzed_comments"] > 20)


def main() -> int:
    print("=" * 60)
    print("  comment scrapper test suite")
    print("=" * 60)
    test_normalize()
    test_relevance()
    test_sentiment()
    test_intent_and_segments()
    test_lead_grading()
    test_fixtures()
    test_comment_model()
    test_reddit_client()
    test_threads_client()
    test_end_to_end()
    test_multi_source_pipeline()
    test_permalinks()
    test_pdf_export()
    test_web_server()

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"  {len(FAILURES)} FAILED: {', '.join(FAILURES)}")
        return 1
    print("  All tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

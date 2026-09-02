# Zorvex SNS Listening — Social Comment Intelligence

**Plan B baseline** · Team SISKAMLING · I'M IN BUSAN Impact Hackathon 2026

Searches social platforms for conversation about stevia tomatoes and competing
premium/healthy food products in Indonesia, filters out the noise, and turns what's
left into named customer segments, graded leads, and marketing recommendations.

Sources: **YouTube** (primary), **Reddit** (optional), **Threads** (limited — read
the caveats before relying on it).

---

## Quick start

```bash
cd hackathon-busan-commentscrapperanalysis
pip install -r requirements.txt     # one dependency: requests

python serve.py                     # dashboard at http://localhost:3333
```

That opens the web dashboard, where you can start a run, watch it progress, and
read the results. Prefer the terminal? `python run.py` does the same thing headless
and writes a report to `data/output/latest_report.md`.

To run against live YouTube data:

```bash
cp .env.example .env                # then paste your key into .env
python run.py --source youtube --max-queries 3
```

Run the tests:

```bash
python tests/test_pipeline.py       # 98 checks, no pytest needed
```

---

## Dashboard

```bash
python serve.py                 # http://localhost:3333, opens a browser tab
python serve.py --lan           # also reachable from other devices (see below)
python serve.py --port 8080     # different port
python serve.py --no-browser    # don't auto-open
```

A single page that runs the pipeline and shows the results — no build step, no
`npm install`, no Flask. It is Python's stdlib `http.server` plus vanilla JS, so a
teammate clones the repo and runs one command.

| Section | Shows |
|---|---|
| **Run analysis** | Source, query count, threshold, analyzer, PDF toggle — then a live progress bar and streaming log while the pipeline runs |
| **Overview** | Stat tiles: fetched, relevant, qualified leads, sentiment, segments — plus download links for the MD/PDF/CSV/JSON |
| **Collection funnel** | How many fetched comments survived filtering, and what the survivors are about |
| **Lead grades** | A–D distribution against the A4 rubric, with a table view |
| **Topics & sentiment** | What the conversation is about; positive/neutral/negative split |
| **Customer segments** | Ranked by volume, with per-segment cards: size, sentiment, topics, and real quotes |
| **Recommendations** | Channel, angle, content idea, and the objection to fix — ranked by qualified leads |

Past runs stay in the dropdown, so you can re-open any earlier analysis without
re-running it. The live-API controls are hidden and disabled when no
`YOUTUBE_API_KEY` is configured, so the offline path can't fail confusingly.

**Chart colours are validated, not eyeballed.** Magnitude bars use a single-hue
sequential blue ramp; sentiment uses a diverging blue↔red pair with a gray
midpoint; lead grades use an ordinal blue ramp with monotone lightness. Each was
checked with the data-viz palette validator in **both** light and dark mode for
colour-vision-deficiency separation and contrast.

### Opening it to other devices

By default the server binds `127.0.0.1` — **loopback only**, meaning this machine
and nothing else. Another laptop typing your IP gets "connection refused" because
nothing is listening on the LAN interface, no matter what IP it uses.

To share it on your network:

```bash
python serve.py --lan
```

That binds `0.0.0.0` (all interfaces) and prints the exact URLs to hand out:

```
  Bound to     : 0.0.0.0:3333
  This machine : http://localhost:3333
  On your LAN  : http://192.168.45.13:3333
```

**There is no login.** Anyone who can reach that URL can start runs — spending your
YouTube API quota — and download every generated report. That is why it is opt-in
rather than the default. On a hackathon or home network that is usually fine; on
open public Wi-Fi, don't.

If a device still can't connect, work down this list:

| Check | How |
|---|---|
| **Bound to the LAN?** | The banner must say `0.0.0.0`, not `127.0.0.1`. `netstat -ano \| findstr :3333` should show `0.0.0.0:3333 LISTENING`. |
| **Same network?** | Both devices on the same Wi-Fi, with IPs in the same subnet (e.g. both `192.168.45.x`). Phone hotspots and guest SSIDs are usually separate networks. |
| **Router client isolation** | Guest networks and many hotel/café APs block device-to-device traffic entirely. Nothing on your machine can fix this — use a different network or a phone hotspot. |
| **Windows Firewall** | Inbound Python must be allowed **for the active profile**. Check the profile with `Get-NetConnectionProfile`, then confirm a matching rule exists — a Public-profile rule does nothing on a Private network and vice versa. |
| **Right IP?** | Use the one the banner prints. Ignore VirtualBox/VMware adapters (often `192.168.56.x`) — those are host-only and unreachable from other machines. |

To add a firewall rule explicitly (run as Administrator, once):

```powershell
New-NetFirewallRule -DisplayName "SNS Listening dashboard" -Direction Inbound `
  -Protocol TCP -LocalPort 3333 -Action Allow -Profile Any
```

---

## Sources — what each one can actually give you

| Source | Reach | What it returns | Setup |
|---|---|---|---|
| **YouTube** | Public comments on *any* video | Full comment threads + replies, the richest signal by far | Paste an API key |
| **Reddit** | Public comments on *any* post | Full nested comment trees | Free OAuth "script" app, ~2 min |
| **Threads** | Public **posts** only | Top-level posts matching a keyword — **not** replies to other people's posts | Meta app + OAuth + app review |

**YouTube is primary and should stay that way.** Instagram's and TikTok's official
APIs only return comments on accounts you *own*, so category-level listening there
means scraping — fragile and against their terms. YouTube's Data API exposes public
comments on any video with just a key.

**Reddit needs OAuth now.** Anonymous `.json` access is closed: `www.reddit.com`
returns 403 and `old.reddit.com` answers 200 but redirects to a login page (verified
2026-09). A free "script" app at https://www.reddit.com/prefs/apps fixes it — the
setup steps are in `src/reddit_client.py` and `.env.example`. Rate limit is 100
queries/minute, no daily quota.

Be realistic about Reddit's value here: Indonesian food discussion on Reddit is
thin. Its `search_queries.reddit` pool is deliberately English-leaning, because what
Reddit gives you is **category** listening (health, diet, premium fruit) rather than
**Indonesia** listening. Useful for the category-creation story, weak for local
market sizing.

**Threads is the weak one, structurally.** The Threads API cannot return replies to
posts you don't own — only your own. Keyword search returns top-level posts and
requires the `threads_keyword_search` permission, which needs Meta app review. So
Threads contributes posts *mentioning* your keywords, not conversation *about* them.
The `src/threads_client.py` module is written to Meta's documented contract but is
**unverified against the live API** — treat your first successful run as its test.

For Zorvex's *own* Instagram/Threads account, the Instagram Graph API on their own
media is the easy, supported path — a different integration that needs none of the
above.

### Running multiple sources

```bash
python run.py --source youtube reddit            # both, merged into one analysis
python run.py --source reddit --subreddits indonesia nutrition loseit
```

Sources with missing credentials are **skipped with a warning, not fatal** — a run
with YouTube configured and Reddit not still produces a full report, and the
`per_source` block in `analysis_*.json` records what was skipped and why. When more
than one platform contributes, the report and dashboard add a platform breakdown and
tag every quote with where it came from.

---

## What it does

```
  YouTube Data API v3
         │
         ▼
  ① SEARCH          search.list across product / competitor / category queries
         │
         ▼
  ② FETCH           commentThreads.list — top-level comments + replies, paginated
         │
         ▼
  ③ FILTER          score every comment against the taxonomy; drop off-topic,
         │          giveaway spam, and comments too short to analyze
         ▼
  ④ ANALYZE         sentiment (id/en/ko) · topic tags · purchase intent ·
         │          lead grade A–D against Zorvex's own criteria
         ▼
  ⑤ SEGMENT         group into the segments Zorvex named, with size, sentiment,
         │          top topics, keywords, and representative quotes
         ▼
  ⑥ RECOMMEND       per segment: channel + message angle + content idea,
                    ranked by qualified leads, plus objections to fix
         │
         ▼
  report.md + analysis.json + comments.csv
```

---

## The design decision that matters

**This system does not discover who the customer is. Zorvex already told us.**

In the Q&A of 2026-08-27 they gave a complete answer to that question:

- **A3 — target customer:** B2B decision-makers are the Fresh Food Buyer / Category
  Manager / Purchasing Manager / MD at supermarkets, premium marts, and fresh-food
  platforms. B2C keywords are **K-Food, Healthy Food, Diet, Wellness, Premium Fruit,
  Sweet Tomato**.
- **A4 — what makes a good lead:** already interested in health/diet/K-Food/premium;
  values taste and quality enough to pay more than for ordinary tomatoes; shows clear
  buy or re-buy intent; buys food online; likely to buy repeatedly rather than out of
  one-off curiosity. Low-quality: little product relevance, event-only participation,
  or extreme price sensitivity.

So a tool that "discovers segments from scratch" would be solving a problem they have
already solved. What they **don't** have is the measurement layer:

| They know | They don't know — this system supplies it |
|---|---|
| Who they want to reach | How much real conversation actually sits behind each stated target |
| What a good lead looks like | How many qualified leads by that definition exist, and where |
| Which channels to research on | What each segment is actually saying — and what's blocking them |

Those criteria are encoded directly in [`config/taxonomy.json`](config/taxonomy.json)
(segments, keywords) and in `RulesAnalyzer.lead_score()` (the A4 rubric as a 0–100
score). **Change what Zorvex said, and the analysis changes** — no code edit required.

---

## Output

Every run writes three files to `data/output/`:

| File | For |
|---|---|
| `report_<tag>.md` | The presentable artifact — funnel, segments, recommendations. Also copied to `latest_report.md`. |
| `analysis_<tag>.json` | Machine-readable; feed this to a dashboard/landing page. |
| `comments_<tag>.csv` | Every analyzed comment with its grade, sentiment, topics, and segment — open in Excel to audit any number in the report. |

**Every quoted comment links back to its source.** Sample quotes in the report, the
dashboard, and the recommendation evidence all carry an `open ↗` link to the exact
YouTube comment (`watch?v=<video>&lc=<comment>` deep-links and highlights it), plus
the video title for context. The CSV carries a `permalink` column for all of them,
not just the quoted ones. Nothing presented as evidence has to be taken on trust —
click through and read the original.

### PDF export

```bash
python run.py --source youtube --pdf     # export as part of the run
python to_pdf.py                         # convert the newest existing report
python to_pdf.py data/output/report_live.md --out pitch.pdf
python to_pdf.py --all                   # convert every report in data/output
```

This adds `report_<tag>.pdf` (and the intermediate `.html`) beside the Markdown.
Rendering shells out to **headless Edge or Chrome**, which ship on Windows and
handle Korean, Indonesian, and emoji with system fonts — no LaTeX, no wkhtmltopdf,
no extra `pip install`. The layout is print-tuned: A4, one section per page, table
headers repeating across page breaks, and no rows split mid-cell.

If no Chromium-family browser is found, the styled HTML is still written and can be
printed from any browser with Ctrl+P. Point `PDF_BROWSER` at a binary to override
detection.

### Lead grading (the A4 rubric, as code)

| Grade | Score | Meaning |
|---|---|---|
| **A** | 65–100 | Strong category fit + clear buy/re-buy intent |
| **B** | 45–64 | Good fit, some intent |
| **C** | 28–44 | Interested but unqualified |
| **D** | 0–27 | Low relevance, or price-only interest (A4's explicit low-quality lead) |

Points come from: stated segment fit (up to 30) · values taste/quality (12) ·
purchase intent (up to 24) · online-buying signals (10) · sentiment (±10) ·
product-specificity of the mention (up to 10) · community likes (up to 6).

---

## CLI reference

```
python run.py [options]

  --source S [S ...]            fixtures | youtube | reddit | threads (one or more)
  --subreddits R [R ...]        restrict Reddit search to these subreddits
  --query-sets core competitor category
                                which query pools to draw from
  --max-queries N               max searches; each costs 100 quota units (default 6)
  --videos-per-query N          videos per search (default 5)
  --comments-per-video N        comments per video (default 100)
  --threshold F                 relevance cutoff; lower = wider net (default 1.0)
  --min-segment-size N          hide segments smaller than this (default 1)
  --analyzer {rules,llm}        rules = deterministic lexicon; llm = Gemini-assisted
  --no-cache                    bypass the local API response cache
  --pdf                         also export the report as PDF
  --tag NAME                    output filename tag (default: UTC timestamp)
  --quiet
```

### API quota

Default free quota is **10,000 units/day**:

| Call | Cost | Returns |
|---|---|---|
| `search.list` | **100** | up to 50 videos |
| `commentThreads.list` | 1 | up to 100 comments |

So searches are the expensive part — `--max-queries 6` spends 600 units and can pull
several thousand comments. **Every API response is cached** to `data/raw/cache/`, so
re-running the same queries during development costs zero additional quota. Use
`--no-cache` to force fresh data.

---

## Two analyzers

**`--analyzer rules`** (default) — lexicon and rules. Deterministic, free, and every
number traces back to a matched term when a mentor asks "why did you score it that
way?" This is the baseline, and it is what the demo should run on.

**`--analyzer llm`** — sends comment batches to Gemini for sentiment, topic, intent,
and segment judgment, which catches sarcasm and slang a lexicon misses. Needs
`pip install google-genai` and `GEMINI_API_KEY`. Calls rotate through a list of
Gemini models (`GEMINI_MODELS` in `.env`, comma-separated) batch by batch, failing
over to the next model on error — this spreads load across each model's separate
free-tier quota. It produces the identical output shape, so everything downstream
is unchanged, and any failed batch (all models exhausted) falls back to the rules
result rather than aborting the run.

---

## Tuning it

Almost everything lives in [`config/taxonomy.json`](config/taxonomy.json) — no code
changes needed:

| To change… | Edit |
|---|---|
| What counts as relevant | `product_core` / `brand` / `competitor` / `category` term lists |
| The segments themselves | `segments[]` — id, name, keywords, `lead_value` |
| What gets searched | `search_queries.core` / `.competitor` / `.category` |
| Topic tagging | `topics` |
| Intent detection | `purchase_intent` |
| Spam filtering | `disqualifiers` |

Sentiment words live in [`config/sentiment_lexicon.json`](config/sentiment_lexicon.json).
Marketing playbooks (channel / angle / content per segment) live in
`src/recommend.py` → `SEGMENT_PLAYBOOK`.

**If the Unsegmented bucket grows, the taxonomy is going stale** — read those comments
in the CSV, add the recurring terms, and re-run.

---

## Layout

```
hackathon-busan-commentscrapperanalysis/
├── run.py                       CLI entry point
├── serve.py                     dashboard entry point (localhost:3333)
├── to_pdf.py                    convert an existing report to PDF
├── requirements.txt
├── .env.example                 copy to .env, add your key
├── config/
│   ├── taxonomy.json            ← segments, keywords, queries (tune here)
│   └── sentiment_lexicon.json   id/en/ko polarity words
├── src/
│   ├── config.py                config + .env loading
│   ├── textutil.py              normalization, multilingual term matching
│   ├── comment.py               platform-neutral Comment record
│   ├── youtube_client.py        YouTube Data API v3 + caching + quota tracking
│   ├── reddit_client.py         Reddit OAuth API + rate limiting
│   ├── threads_client.py        Threads keyword search (limited; see caveats)
│   ├── relevance.py             relevance scoring and noise filtering
│   ├── analyze.py               sentiment, topics, intent, lead grading
│   ├── llm_analyze.py           optional Gemini-assisted analyzer
│   ├── segments.py              aggregate comments into segment profiles
│   ├── recommend.py             segment → channel / angle / content
│   ├── report.py                markdown + JSON + CSV writers
│   ├── pdf_export.py            markdown -> styled HTML -> PDF
│   ├── pipeline.py              orchestration
│   └── cli.py                   argument parsing
├── data/
│   ├── fixtures/                offline 80-comment sample set
│   ├── raw/                     fetched comments + API cache (gitignored)
│   └── output/                  generated reports (gitignored)
└── tests/test_pipeline.py       98 checks, no pytest needed
```

---

## Known limits — say these out loud rather than hide them

1. **The fixture set is synthetic.** `data/fixtures/sample_comments.json` was written
   to exercise the pipeline, not scraped from YouTube. It is realistic but it is not
   evidence. Any number presented as a finding must come from a `--source youtube` run.
2. **Stevia tomato barely exists in Indonesia** (Zorvex's own A7). Expect very few
   direct product mentions — that is *the finding*, not a bug. The system is built to
   listen to adjacent interest (health / diet / K-Food / premium fruit) precisely
   because the category itself has no search volume yet to capture.
3. **These platforms ≠ the whole market.** Instagram and TikTok are where Zorvex's
   audience actually is; YouTube and Reddit are where comments are legally reachable
   at category scale. Treat the result as a representative sample, not a census —
   and note Reddit skews global/English, not Indonesian.
4. **The lexicon is not a language model.** Sarcasm and heavy slang will be misread by
   `--analyzer rules`. Run `--analyzer llm` on the final dataset if accuracy matters
   more than determinism.
5. **B2B is not covered yet.** A3 weights B2B buyers (Fresh Food Buyer / Category
   Manager / MD) equally with consumers, and comment listening cannot find them. That
   half needs a different source — this is the most honest next build.

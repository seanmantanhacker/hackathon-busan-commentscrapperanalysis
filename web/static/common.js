/* Zorvex SNS Listening — shared rendering helpers.
   Loaded before app.js (full dashboard) and present.js (panel-facing summary
   page) so both stay visually identical for the pieces they share, instead of
   two copies of the same card markup drifting apart. */

window.SNS = (() => {
  "use strict";

  const esc = (value) => String(value ?? "").replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const pct = (value) => `${(value * 100).toFixed(1)}%`;
  const num = (value) => Number(value ?? 0).toLocaleString();

  const GRADE_MEANING = {
    A: "Strong fit + clear buy/re-buy intent",
    B: "Good category fit, some intent",
    C: "Interested but unqualified",
    D: "Low relevance or price-only interest",
  };

  /** Horizontal magnitude bars. `variant` switches the ordinal grade ramp on. */
  function barChart(rows, { variant = "" } = {}) {
    if (!rows.length) return '<p class="muted small">No data.</p>';
    const max = Math.max(...rows.map((r) => r.value), 1);
    return `<div class="bars">${rows.map((row) => {
      const width = Math.max(1.5, (row.value / max) * 100);
      const cls = variant === "grade" ? ` bar-row--grade-${esc(row.key)}` : "";
      const title = row.title ? ` title="${esc(row.title)}"` : "";
      return `<div class="bar-row${cls}">
        <span class="bar-row__label"${title}>${esc(row.label)}</span>
        <div class="bar-row__track"><div class="bar-row__fill" style="width:${width}%"></div></div>
        <span class="bar-row__value">${num(row.value)}${
          row.suffix ? `<span> ${esc(row.suffix)}</span>` : ""}</span>
      </div>`;
    }).join("")}</div>`;
  }

  /** Headline stat tiles + the matching written-out glossary. Pure — caller assigns the HTML. */
  function buildStatTiles(data) {
    const overall = data.overall || {};
    const collection = data.collection || {};
    const total = overall.analyzed_comments || 0;
    const qualified = overall.qualified_leads || 0;
    const sentiment = overall.avg_sentiment ?? 0;

    const tiles = [
      {
        label: "Comments fetched", value: num(collection.fetched),
        sub: `${num((data.run || {}).videos)} videos searched`,
        help: "Every comment pulled from the source APIs, before any filtering. "
            + "Includes off-topic chatter, spam and one-word replies.",
      },
      {
        label: "Relevant", value: num(total),
        sub: `${pct(collection.keep_rate || 0)} keep rate`,
        help: "Comments that survived filtering — the ones actually worth reading. "
            + "A comment is kept only if it mentions the product, a competitor, or a "
            + "category keyword from the taxonomy, scores at or above the relevance "
            + "threshold, is not giveaway/promo spam, and is at least 3 words long. "
            + "The keep rate is what share of the raw haul that was.",
      },
      {
        label: "Qualified leads", value: num(qualified),
        sub: total ? `${pct(qualified / total)} of relevant · grade A/B` : "—",
        help: "Relevant comments graded A or B against Zorvex's OWN definition of a "
            + "good lead (Q&A A4): already interested in health/diet/K-Food/premium, "
            + "values taste over price, shows buy or re-buy intent, buys food online, "
            + "and looks likely to buy repeatedly. Scored 0–100; A/B means 45+.",
      },
      {
        label: "Avg sentiment",
        value: (sentiment >= 0 ? "+" : "") + sentiment.toFixed(2),
        sub: "−1 to +1",
        help: "Average tone across the relevant comments, from −1 (very negative) to "
            + "+1 (very positive). Computed from an Indonesian/English/Korean word list "
            + "that also handles negation, so ‘gak enak’ counts as negative, not positive.",
      },
      {
        label: "Segments", value: num((data.segments || []).length),
        sub: "from Zorvex's stated targets",
        help: "How many of Zorvex's stated target audiences (Q&A A3) actually showed up "
            + "in the conversation — plus an 'Unsegmented' bucket for relevant comments "
            + "that matched no segment keyword. These are NOT discovered by us; Zorvex "
            + "named them and this measures how much real conversation each one has.",
      },
    ];
    const platforms = overall.platform_mix || {};
    if (Object.keys(platforms).length > 1) {
      tiles.push({
        label: "Platforms",
        value: Object.keys(platforms).length,
        sub: Object.entries(platforms).map(([k, v]) => `${k} ${v}`).join(" · "),
      });
    }

    const tilesHtml = tiles.map((t) => `<div class="tile">
      <div class="tile__label">${esc(t.label)}${
        t.help ? `<span class="tile__info" tabindex="0" role="note" aria-label="${esc(t.help)}" title="${esc(t.help)}">i</span>` : ""}</div>
      <div class="tile__value">${esc(t.value)}</div>
      <div class="tile__sub">${esc(t.sub)}</div>
    </div>`).join("");

    const glossaryHtml = tiles
      .filter((t) => t.help)
      .map((t) => `<div class="glossary__row">
        <dt class="glossary__term">${esc(t.label)}</dt>
        <dd class="glossary__def">${esc(t.help)}</dd>
      </div>`).join("")
      + `<div class="glossary__row">
        <dt class="glossary__term">Lead grades A / B / C / D</dt>
        <dd class="glossary__def">Points come from: stated segment fit (up to 30),
          values taste or freshness (12), purchase intent (up to 24), signals of buying
          food online (10), sentiment (±10), how product-specific the mention is (up to 10),
          and community likes (up to 6). A = 65+, B = 45–64, C = 28–44, D = under 28.
          Price-only interest scores low on purpose — A4 calls it a low-quality lead.</dd>
      </div>`;

    return { tilesHtml, glossaryHtml };
  }

  function quoteHtml(q) {
    const link = q.permalink
      ? ` · <a class="quote__link" href="${esc(q.permalink)}" target="_blank" rel="noopener noreferrer">open ↗</a>`
      : "";
    const src = q.source ? ` · ${esc(q.source)}` : "";
    const translation = q.text_ko
      ? `<div class="quote__translation">translated (KO): ${esc(q.text_ko)}</div>`
      : "";
    return `
    <div class="quote quote--${esc(q.sentiment)}">"${esc(q.text)}"
      <span class="quote__meta">${esc(q.platform || "")} · grade ${esc(q.lead_grade)} · intent ${esc(q.intent)} · ${num(q.likes)} likes${src}${link}</span>
      ${translation}
    </div>`;
  }

  /** Segment cards (size, sentiment, translated sample quotes). `withChart` also
   * returns a volume bar chart — the full dashboard wants it, the panel-facing
   * summary page doesn't. */
  function buildSegmentCards(data, { withChart = false, quotesPerCard = 2 } = {}) {
    const segments = data.segments || [];
    const cardsHtml = segments.map((s) => {
      const topics = (s.top_topics || []).slice(0, 4)
        .map(([t, c]) => `<span class="chip">${esc(t)} · ${c}</span>`).join("");
      const quotes = (s.sample_quotes || []).slice(0, quotesPerCard).map(quoteHtml).join("");
      return `<article class="card${s.lead_value === "low" ? " card--low" : ""}">
        <div class="card__head">
          <div><div class="card__name">${esc(s.name)}</div>
               <div class="card__ko">${esc(s.name_ko || "")}</div></div>
          <div class="card__share">${pct(s.share)}</div>
        </div>
        <p class="card__desc">${esc(s.description)}</p>
        <div class="card__stats">
          <div class="card__stat"><b>${num(s.size)}</b>comments</div>
          <div class="card__stat"><b>${num(s.qualified_leads)}</b>qualified</div>
          <div class="card__stat"><b>${s.avg_sentiment >= 0 ? "+" : ""}${Number(s.avg_sentiment).toFixed(2)}</b>sentiment</div>
          <div class="card__stat"><b>${s.avg_lead_score}</b>avg score</div>
        </div>
        <div class="chips">${topics}</div>
        <div class="quotes">${quotes}</div>
      </article>`;
    }).join("");

    if (!withChart) return { cardsHtml };

    const chartHtml = barChart(
      segments.map((s) => ({
        label: s.name, value: s.size, suffix: `(${s.qualified_leads} qual.)`,
        title: `${s.name} — ${s.size} comments, ${s.qualified_leads} qualified`,
      })).sort((a, b) => b.value - a.value)
    );
    return { chartHtml, cardsHtml };
  }

  /** Recommendation cards, ranked by qualified leads, with translated evidence quotes. */
  function buildRecommendations(data) {
    return (data.recommendations || []).map((r) => {
      const row = (key, value, warn) => value
        ? `<div class="rec__row${warn ? " rec__row--warn" : ""}">
             <span class="rec__key">${esc(key)}</span><span class="rec__val">${esc(value)}</span></div>`
        : "";
      return `<article class="rec">
        <div class="rec__head">
          <span class="rec__rank">${r.priority}</span>
          <span class="rec__name">${esc(r.segment_name)}</span>
          <span class="rec__badges">
            <span class="badge">${num(r.size)} comments</span>
            <span class="badge ${r.qualified_leads > 0 ? "badge--ok" : "badge--muted"}">${num(r.qualified_leads)} qualified</span>
          </span>
        </div>
        <div class="rec__rows">
          ${row("Channel", r.channel)}
          ${row("Angle", r.message_angle)}
          ${row("Content", r.content_idea)}
          ${row("Why", r.rationale)}
          ${row("Fix first", r.objection_to_address, true)}
        </div>
        ${r.evidence_quote ? `<div class="rec__evidence">"${esc(r.evidence_quote)}"${
          r.evidence_permalink
            ? ` <a class="quote__link" href="${esc(r.evidence_permalink)}" target="_blank" rel="noopener noreferrer">open ↗</a>`
            : ""}${
          r.evidence_quote_ko
            ? `<div class="quote__translation">translated (KO): ${esc(r.evidence_quote_ko)}</div>`
            : ""}</div>` : ""}
      </article>`;
    }).join("");
  }

  function initThemeToggle(buttonEl) {
    const saved = (() => { try { return localStorage.getItem("sns-theme"); } catch { return null; } })();
    if (saved) document.documentElement.setAttribute("data-theme", saved);
    buttonEl.addEventListener("click", () => {
      const isDark = document.documentElement.getAttribute("data-theme") === "dark"
        || (!document.documentElement.hasAttribute("data-theme")
            && matchMedia("(prefers-color-scheme: dark)").matches);
      const next = isDark ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      try { localStorage.setItem("sns-theme", next); } catch { /* private mode */ }
    });
  }

  async function fetchReportList() {
    const response = await fetch("/api/reports");
    if (!response.ok) return [];
    return (await response.json()).reports || [];
  }

  async function fetchResults(tag) {
    const url = tag ? `/api/results?tag=${encodeURIComponent(tag)}` : "/api/results";
    const response = await fetch(url);
    if (!response.ok) return null;
    return response.json();
  }

  return {
    esc, pct, num, barChart, GRADE_MEANING,
    buildStatTiles, buildSegmentCards, buildRecommendations,
    initThemeToggle, fetchReportList, fetchResults,
  };
})();

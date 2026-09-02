/* Zorvex SNS Listening — dashboard client.
   Vanilla JS, no build step and no CDN: the whole point is that a teammate can
   clone the repo, run `python serve.py`, and have it work offline. */

(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const POLL_MS = 500;
  const { esc, pct, num, barChart, GRADE_MEANING, buildStatTiles, buildSegmentCards,
          buildRecommendations, initThemeToggle } = window.SNS;

  const el = {
    sources: $("sources"), maxQueries: $("maxQueries"), videosPerQuery: $("videosPerQuery"),
    commentsPerVideo: $("commentsPerVideo"), threshold: $("threshold"), analyzer: $("analyzer"),
    wantPdf: $("wantPdf"), useCache: $("useCache"), runBtn: $("runBtn"),
    keyBadge: $("keyBadge"), quotaHint: $("quotaHint"), themeToggle: $("themeToggle"),
    progressWrap: $("progressWrap"), progressMsg: $("progressMsg"), progressPct: $("progressPct"),
    progressBar: $("progressBar"), progressBarEl: $("progressBarEl"), progressLog: $("progressLog"),
    runError: $("runError"),
    resultsPage1: $("resultsPage1"), resultsPage2: $("resultsPage2"), emptyState: $("emptyState"),
    tabRun: $("tabRun"), tabDetails: $("tabDetails"), pageRun: $("page-run"), pageDetails: $("page-details"),
    statTiles: $("statTiles"), runMeta: $("runMeta"), downloads: $("downloads"),
    glossary: $("glossary"),
    sourceTable: $("sourceTable"), nextBuilds: $("nextBuilds"),
    roadmapBasis: $("roadmapBasis"),
    reportPicker: $("reportPicker"), funnel: $("funnel"),
    gradeChart: $("gradeChart"), gradeTable: $("gradeTable"),
    topicChart: $("topicChart"), sentimentChart: $("sentimentChart"),
    segmentChart: $("segmentChart"), segmentCards: $("segmentCards"),
    recommendations: $("recommendations"), notes: $("notes"),
  };

  let pollTimer = null;
  let serverConfig = { has_youtube_key: false, pdf_available: false };

  /* ------------------------------------------------------------- rendering */

  function renderStats(data) {
    const { tilesHtml, glossaryHtml } = buildStatTiles(data);
    el.statTiles.innerHTML = tilesHtml;
    // A written-out glossary as well as the tooltips — a judge reading over a
    // shoulder shouldn't have to hover to find out what a number means.
    el.glossary.innerHTML = glossaryHtml;

    const run = data.run || {};
    const quota = run.quota;
    el.runMeta.textContent = [
      `Generated ${run.generated_at || "—"}`,
      `sources: ${(run.sources || [run.source]).filter(Boolean).join(" + ") || "—"}`,
      `analyzer: ${run.analyzer || "—"}`,
      quota ? `quota used: ${quota.quota_units_used}/10,000 units` : null,
    ].filter(Boolean).join(" · ");
  }

  function renderFunnel(data) {
    const c = data.collection || {};
    const buckets = c.buckets || {};
    const rows = [
      { label: "Fetched", value: c.fetched || 0 },
      { label: "Relevant", value: c.relevant || 0 },
      { label: "Off topic", value: c.dropped_off_topic || 0 },
      { label: "Spam / short", value: c.dropped_spam_or_too_short || 0 },
    ];
    const bucketRows = Object.entries(buckets).map(([key, value]) => ({ label: key, value }));
    el.funnel.innerHTML = barChart(rows) +
      (bucketRows.length
        ? `<p class="muted small" style="margin-top:16px">What the relevant comments are about:</p>${barChart(bucketRows)}`
        : "");
  }

  function renderGrades(data) {
    const grades = (data.overall || {}).lead_grades || {};
    const rows = ["A", "B", "C", "D"].map((g) => ({
      key: g, label: `Grade ${g}`, value: grades[g] || 0, title: GRADE_MEANING[g],
    }));
    el.gradeChart.innerHTML = barChart(rows, { variant: "grade" });
    // Table view doubles as the relief for any low-contrast ramp step.
    el.gradeTable.innerHTML = `<thead><tr><th>Grade</th><th>Meaning</th><th class="num">Count</th></tr></thead>
      <tbody>${rows.map((r) => `<tr>
        <td><strong>${r.key}</strong></td><td>${esc(GRADE_MEANING[r.key])}</td>
        <td class="num">${num(r.value)}</td></tr>`).join("")}</tbody>`;
  }

  function renderTopics(data) {
    const topics = (data.overall || {}).top_topics || [];
    el.topicChart.innerHTML = barChart(topics.map(([label, value]) => ({ label, value })));
  }

  function renderSentiment(data) {
    const mix = (data.overall || {}).sentiment_mix || {};
    const parts = [
      { key: "pos", label: "Positive", value: mix.positive || 0 },
      { key: "neutral", label: "Neutral", value: mix.neutral || 0 },
      { key: "neg", label: "Negative", value: mix.negative || 0 },
    ];
    const total = parts.reduce((sum, p) => sum + p.value, 0) || 1;

    el.sentimentChart.innerHTML = `
      <div class="stack">${parts.filter((p) => p.value > 0).map((p) =>
        `<div class="stack__seg stack__seg--${p.key}" style="flex:${p.value} 1 0"
              title="${esc(p.label)}: ${p.value}"></div>`).join("")}</div>
      <div class="legend">${parts.map((p) => `<span class="legend__item">
        <span class="legend__swatch legend__swatch--${p.key}"></span>
        ${esc(p.label)} <span class="legend__value">${num(p.value)}</span>
        <span>(${pct(p.value / total)})</span></span>`).join("")}</div>`;
  }

  function renderSegments(data) {
    // The chart encodes conversation volume, so it is ranked by volume. The
    // cards below stay in the report's priority order (qualified leads first).
    const { chartHtml, cardsHtml } = buildSegmentCards(data, { withChart: true });
    el.segmentChart.innerHTML = chartHtml;
    el.segmentCards.innerHTML = cardsHtml;
  }

  function renderRecommendations(data) {
    el.recommendations.innerHTML = buildRecommendations(data);
  }

  function renderNotes(data) {
    el.notes.innerHTML = (data.strategic_notes || [])
      .map((note) => `<li>${esc(note)}</li>`).join("");
  }

  function renderDownloads(tag) {
    if (!tag) { el.downloads.innerHTML = ""; return; }
    const files = [
      ["Markdown", `report_${tag}.md`], ["PDF", `report_${tag}.pdf`],
      ["CSV", `comments_${tag}.csv`], ["JSON", `analysis_${tag}.json`],
    ];
    el.downloads.innerHTML = files
      .map(([label, name]) => `<a href="/api/download/${encodeURIComponent(name)}">${label}</a>`)
      .join("");
  }

  function render(data, tag) {
    renderStats(data); renderFunnel(data); renderGrades(data);
    renderTopics(data); renderSentiment(data); renderSegments(data);
    renderRecommendations(data); renderNotes(data); renderDownloads(tag);
    el.resultsPage1.hidden = false;
    el.resultsPage2.hidden = false;
    el.emptyState.hidden = true;
  }


  /* ------------------------------------------------------------- roadmap */

  const STATUS_LABEL = {
    active: ["Active", "ok"],
    ready: ["Ready to enable", "ok"],
    limited: ["Limited", "warn"],
    paid: ["Paid", "warn"],
    blocked: ["Own account only", "muted"],
    unavailable: ["No API", "muted"],
  };

  const VALUE_LABEL = { high: "High", "low-medium": "Low–med", medium: "Medium", low: "Low" };

  async function loadRoadmap() {
    let catalog;
    try {
      catalog = await (await fetch("/api/sources")).json();
    } catch { return; }

    const rows = (catalog.sources || []).map((src) => {
      const [label, tone] = STATUS_LABEL[src.status] || [src.status, "muted"];
      // `configured` comes from the live server, so an "active" row that isn't
      // actually wired up says so instead of quietly lying.
      const live = src.configured === true
        ? ' <span class="badge badge--ok">configured</span>'
        : src.configured === false ? ' <span class="badge badge--muted">not set up</span>' : "";
      return `<tr>
        <td><strong>${esc(src.name)}</strong><br/><span class="badge badge--${tone}">${esc(label)}</span>${live}</td>
        <td><strong>${esc(src.cost)}</strong><div class="muted small">${esc(src.cost_detail)}</div></td>
        <td>${esc(src.setup)}</td>
        <td>${esc(src.reads)}</td>
        <td>${esc(VALUE_LABEL[src.indonesia_value] || src.indonesia_value)}</td>
      </tr>
      <tr class="datatable__note"><td colspan="5">${esc(src.verdict)}
        <span class="muted"> · basis: ${esc(src.basis)}</span></td></tr>`;
    }).join("");

    el.sourceTable.innerHTML = `<colgroup>
        <col class="c-source"/><col class="c-cost"/><col class="c-setup"/>
        <col class="c-reads"/><col class="c-value"/>
      </colgroup><thead><tr>
        <th>Source</th><th>Cost</th><th>Setup</th><th>What it reads</th><th>Value for Indonesia</th>
      </tr></thead><tbody>${rows}</tbody>`;

    el.nextBuilds.innerHTML = (catalog.next_builds || []).map((b) => `
      <article class="build">
        <div class="build__head">
          <span class="build__title">${esc(b.title)}</span>
          <span class="badge badge--${b.value === "high" ? "ok" : "muted"}">${esc(b.value)} value</span>
        </div>
        <div class="build__meta">${esc(b.cost)} · effort: ${esc(b.effort)}</div>
        <p class="build__detail">${esc(b.detail)}</p>
      </article>`).join("");

    el.roadmapBasis.textContent = catalog._meta
      ? `${catalog._meta.measured_baseline}  ·  Last reviewed ${catalog._meta.last_reviewed}.`
      : "";
  }

  /* ------------------------------------------------------------- loading */

  async function loadResults(tag) {
    const url = tag ? `/api/results?tag=${encodeURIComponent(tag)}` : "/api/results";
    const response = await fetch(url);
    if (!response.ok) return false;
    render(await response.json(), tag);
    return true;
  }

  async function loadReportList(selectTag) {
    const response = await fetch("/api/reports");
    if (!response.ok) return;
    const { reports } = await response.json();
    el.reportPicker.innerHTML = reports.map((r) =>
      `<option value="${esc(r.tag)}">${esc(r.tag)} — ${r.analyzed} comments, ${r.source}</option>`).join("");
    if (selectTag) el.reportPicker.value = selectTag;
    el.reportPicker.hidden = reports.length === 0;
  }

  /* ----------------------------------------------------------- the run */

  function setProgress(state) {
    el.progressMsg.textContent = state.message || "Working…";
    el.progressPct.textContent = `${state.percent}%`;
    el.progressBar.style.width = `${state.percent}%`;
    el.progressBarEl.setAttribute("aria-valuenow", String(state.percent));
    el.progressBar.classList.toggle("is-error", state.state === "error");
    if (state.log && state.log.length) {
      el.progressLog.textContent = state.log.join("\n");
      el.progressLog.scrollTop = el.progressLog.scrollHeight;
    }
  }

  function stopPolling() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  }

  function startPolling(tag) {
    stopPolling();
    pollTimer = setInterval(async () => {
      let state;
      try {
        state = await (await fetch("/api/progress")).json();
      } catch { return; }   // transient — keep polling
      setProgress(state);

      if (state.state === "done") {
        stopPolling();
        el.runBtn.disabled = false;
        el.runBtn.textContent = "Run analysis";
        await loadReportList(tag);
        await loadResults(tag);
      } else if (state.state === "error") {
        stopPolling();
        el.runBtn.disabled = false;
        el.runBtn.textContent = "Run analysis";
        el.runError.textContent = state.error || "The run failed.";
        el.runError.hidden = false;
      }
    }, POLL_MS);
  }

  async function startRun() {
    el.runError.hidden = true;
    el.progressWrap.hidden = false;
    el.progressLog.textContent = "";
    el.runBtn.disabled = true;
    el.runBtn.textContent = "Running…";
    setProgress({ percent: 0, message: "Starting…", state: "running" });

    const options = {
      sources: selectedSources(),
      max_queries: Number(el.maxQueries.value),
      videos_per_query: Number(el.videosPerQuery.value),
      comments_per_video: Number(el.commentsPerVideo.value),
      threshold: Number(el.threshold.value),
      analyzer: el.analyzer.value,
      use_cache: el.useCache.checked,
      pdf: el.wantPdf.checked,
    };

    let payload;
    try {
      const response = await fetch("/api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(options),
      });
      payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Could not start the run.");
    } catch (error) {
      el.runBtn.disabled = false;
      el.runBtn.textContent = "Run analysis";
      el.runError.textContent = error.message;
      el.runError.hidden = false;
      return;
    }
    startPolling(payload.tag);
  }

  /* -------------------------------------------------------------- setup */

  /** Which source checkboxes are ticked. */
  function selectedSources() {
    return [...el.sources.querySelectorAll("input:checked")].map((box) => box.value);
  }

  function syncSourceFields() {
    const chosen = selectedSources();
    const live = chosen.some((s) => s !== "fixtures");
    document.querySelectorAll("[data-live-only]")
      .forEach((node) => node.classList.toggle("is-hidden", !live));
    el.quotaHint.textContent = chosen.includes("youtube")
      ? `(~${Number(el.maxQueries.value) * 100} YouTube quota units)` : "";
    el.runBtn.disabled = chosen.length === 0;
  }

  function showPage(name) {
    const isRun = name !== "details";
    el.pageRun.hidden = !isRun;
    el.pageDetails.hidden = isRun;
    el.tabRun.classList.toggle("tab--active", isRun);
    el.tabDetails.classList.toggle("tab--active", !isRun);
    el.tabRun.setAttribute("aria-selected", String(isRun));
    el.tabDetails.setAttribute("aria-selected", String(!isRun));
    try { localStorage.setItem("sns-page", name); } catch { /* private mode */ }
  }

  function initTabs() {
    el.tabRun.addEventListener("click", () => showPage("run"));
    el.tabDetails.addEventListener("click", () => showPage("details"));
    const saved = (() => { try { return localStorage.getItem("sns-page"); } catch { return null; } })();
    if (saved) showPage(saved);
  }

  async function init() {
    initThemeToggle(el.themeToggle);
    initTabs();
    el.runBtn.addEventListener("click", startRun);
    el.sources.addEventListener("change", syncSourceFields);
    el.maxQueries.addEventListener("input", syncSourceFields);
    el.reportPicker.addEventListener("change", (e) => loadResults(e.target.value));

    try {
      serverConfig = await (await fetch("/api/config")).json();
    } catch { /* server restarting — defaults are fine */ }

    // Disable any source whose credentials are missing, and say what's needed.
    const credentials = {
      youtube: [serverConfig.has_youtube_key, "needs YOUTUBE_API_KEY in .env"],
      reddit: [serverConfig.has_reddit, "needs REDDIT_CLIENT_ID + SECRET in .env"],
      threads: [serverConfig.has_threads, "needs THREADS_ACCESS_TOKEN in .env"],
    };
    for (const [name, [ready, why]] of Object.entries(credentials)) {
      const box = el.sources.querySelector(`input[value="${name}"]`);
      if (!box || ready) continue;
      box.disabled = true;
      box.checked = false;
      const label = box.closest(".check");
      label.title = why;
      label.classList.add("check--disabled");
      label.querySelector("span").textContent += " — not configured";
    }

    const ready = Object.entries(credentials).filter(([, [ok]]) => ok).map(([n]) => n);
    if (ready.length) {
      el.keyBadge.textContent = `Live sources: ${ready.join(", ")}`;
      el.keyBadge.className = "badge badge--ok";
    } else {
      el.keyBadge.textContent = "No credentials — offline sample only";
      el.keyBadge.className = "badge badge--warn";
    }
    if (!serverConfig.pdf_available) {
      el.wantPdf.disabled = true;
      el.wantPdf.closest(".check").title = "No Edge/Chrome found for PDF rendering";
    }
    // Don't offer an analyzer that would silently fall back to rules — say why.
    if (!serverConfig.llm_available) {
      const option = el.analyzer.querySelector('option[value="llm"]');
      const reason = serverConfig.llm_blocker || "unavailable";
      option.disabled = true;
      option.textContent = `Gemini-assisted — ${reason}`;
      el.analyzer.title = `Gemini-assisted analysis ${reason}`;
    }
    if (!serverConfig.translation_available) {
      const note = " Korean quote translation is off — run `pip install deep-translator`.";
      const segNote = $("segTranslationNote"), recNote = $("recTranslationNote");
      if (segNote) segNote.textContent = note;
      if (recNote) recNote.textContent = note;
    }

    syncSourceFields();
    await loadRoadmap();
    await loadReportList();
    // Show the most recent run immediately, so the dashboard isn't empty on open.
    if (el.reportPicker.options.length) await loadResults(el.reportPicker.value);
  }

  document.addEventListener("DOMContentLoaded", init);
})();

/* Zorvex SNS Listening — panel-facing summary view.
   Deliberately narrow: headline numbers, segments with (translated) quotes,
   and recommendations. Everything else lives on the full dashboard. */

(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const { esc, buildStatTiles, buildSegmentCards, buildRecommendations,
          initThemeToggle, fetchReportList, fetchResults } = window.SNS;

  const el = {
    reportPicker: $("reportPicker"), themeToggle: $("themeToggle"),
    results: $("results"), emptyState: $("emptyState"),
    statTiles: $("statTiles"), runMeta: $("runMeta"),
    segmentCards: $("segmentCards"), recommendations: $("recommendations"),
  };

  function render(data) {
    el.statTiles.innerHTML = buildStatTiles(data).tilesHtml;

    const run = data.run || {};
    el.runMeta.textContent = [
      `Generated ${run.generated_at || "—"}`,
      `sources: ${(run.sources || [run.source]).filter(Boolean).join(" + ") || "—"}`,
    ].filter(Boolean).join(" · ");

    el.segmentCards.innerHTML = buildSegmentCards(data, { withChart: false }).cardsHtml;
    el.recommendations.innerHTML = buildRecommendations(data);

    el.results.hidden = false;
    el.emptyState.hidden = true;
  }

  async function loadResults(tag) {
    const data = await fetchResults(tag);
    if (!data) return false;
    render(data);
    return true;
  }

  async function loadReportList(selectTag) {
    const reports = await fetchReportList();
    el.reportPicker.innerHTML = reports.map((r) =>
      `<option value="${esc(r.tag)}">${esc(r.tag)} — ${r.analyzed} comments, ${r.source}</option>`).join("");
    if (selectTag) el.reportPicker.value = selectTag;
    el.reportPicker.hidden = reports.length === 0;
  }

  async function init() {
    initThemeToggle(el.themeToggle);
    el.reportPicker.addEventListener("change", (e) => loadResults(e.target.value));

    await loadReportList();
    if (el.reportPicker.options.length) await loadResults(el.reportPicker.value);
  }

  document.addEventListener("DOMContentLoaded", init);
})();

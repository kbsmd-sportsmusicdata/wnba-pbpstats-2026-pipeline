(() => {
  "use strict";

  const payload = JSON.parse(document.getElementById("rfm-data").textContent);
  const candidates = payload.candidates;
  const evidence = payload.evidence;
  const isFixture = payload.meta.mode === "fixture";
  const isLive = payload.meta.mode === "live";
  const {
    buildMetricContext,
    formatEvidenceValue,
    formatMetricChange,
    formatMetricValue,
    formatScore,
    hasPlottableScores,
    scoreWidth,
  } = globalThis.RFMScoreDisplay;

  function node(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  function renderFunnel() {
    const target = document.getElementById("funnel-summary");
    const counts = payload.meta.funnel_counts;
    const items = [
      ["Roster pool", counts.players_considered],
      ["Contender gate", counts.players_considered - (counts.excluded_non_contender_team || 0)],
      ["Reviewed eligibility", counts.players_considered - (counts.excluded_non_contender_team || 0) - (counts.excluded_eligibility_not_reviewed || 0)],
      [isFixture ? "Scored fixtures" : (isLive ? "Live scores" : "Dry-run scores"), counts.players_scored],
    ];
    items.forEach(([label, value], index) => {
      const card = node("article", "funnel-card");
      card.append(node("span", "step", String(index + 1).padStart(2, "0")));
      card.append(node("strong", null, String(value)));
      card.append(node("p", null, label));
      target.append(card);
    });
  }

  function metricBar(label, value, code) {
    const wrap = node("div", "metric");
    if (formatScore(value) === "Unavailable") wrap.classList.add("metric-unavailable");
    const line = node("div", "metric-line");
    line.append(node("span", null, label));
    line.append(node("b", null, formatScore(value)));
    const track = node("div", "track");
    const fill = node("span", `fill fill-${code}`);
    fill.style.width = `${scoreWidth(value)}%`;
    track.append(fill);
    wrap.append(line, track);
    return wrap;
  }

  function renderCards() {
    const target = document.getElementById("score-cards");
    candidates.forEach((candidate) => {
      const card = node("article", "player-card");
      const top = node("div", "player-top");
      const identity = node("div");
      identity.append(node("p", "team-tag", `${candidate.team_abbreviation} · ${candidate.role_label}`));
      identity.append(node("h3", null, candidate.player_name));
      top.append(identity, node("span", "fixture-tag", isFixture ? "FIXTURE" : (isLive ? "LIVE" : "DRY RUN")));
      card.append(top);
      card.append(metricBar("Fulfillment", candidate.fulfillment_score, "ful"));
      card.append(metricBar("Opportunity", candidate.opportunity_score, "opp"));
      card.append(metricBar("Stability", candidate.stability_score, "stb"));
      const button = node("button", "evidence-button", "View evidence →");
      button.type = "button";
      button.dataset.playerId = candidate.player_id;
      card.append(button);
      target.append(card);
    });
  }

  function svgElement(tag, attributes = {}) {
    const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, String(value)));
    return element;
  }

  function renderMatrix() {
    const target = document.getElementById("role-matrix");
    const svg = svgElement("svg", {viewBox: "0 0 820 500", role: "presentation"});
    const plot = {x: 90, y: 42, w: 660, h: 380};
    [[0, 0], [1, 0], [0, 1], [1, 1]].forEach(([column, row]) => {
      const rect = svgElement("rect", {x: plot.x + column * plot.w / 2, y: plot.y + row * plot.h / 2, width: plot.w / 2, height: plot.h / 2, class: `quadrant q-${column}-${row}`});
      svg.append(rect);
    });
    svg.append(svgElement("line", {x1: plot.x + plot.w / 2, y1: plot.y, x2: plot.x + plot.w / 2, y2: plot.y + plot.h, class: "matrix-line"}));
    svg.append(svgElement("line", {x1: plot.x, y1: plot.y + plot.h / 2, x2: plot.x + plot.w, y2: plot.y + plot.h / 2, class: "matrix-line"}));

    const axisX = svgElement("text", {x: plot.x + plot.w / 2, y: 475, class: "axis-label"});
    axisX.textContent = "OPPORTUNITY →";
    svg.append(axisX);
    const axisY = svgElement("text", {x: 25, y: plot.y + plot.h / 2, class: "axis-label", transform: `rotate(-90 25 ${plot.y + plot.h / 2})`});
    axisY.textContent = "FULFILLMENT →";
    svg.append(axisY);

    const plottable = candidates.filter(hasPlottableScores);
    plottable.forEach((candidate, index) => {
      const x = plot.x + Number(candidate.opportunity_score) / 100 * plot.w;
      const y = plot.y + plot.h - Number(candidate.fulfillment_score) / 100 * plot.h;
      const radius = 10 + Number(candidate.stability_score) / 100 * 12;
      const circle = svgElement("circle", {cx: x, cy: y, r: radius, class: `candidate-dot dot-${index}`});
      circle.setAttribute("tabindex", "0");
      circle.setAttribute("aria-label", `${candidate.player_name}: Fulfillment ${formatScore(candidate.fulfillment_score)}, Opportunity ${formatScore(candidate.opportunity_score)}, Stability ${formatScore(candidate.stability_score)}`);
      circle.dataset.playerId = candidate.player_id;
      svg.append(circle);
      const label = svgElement("text", {x: x + radius + 8, y: y + 5, class: "dot-label"});
      label.textContent = candidate.player_name;
      svg.append(label);
    });
    target.append(svg);
    const omitted = candidates.length - plottable.length;
    if (omitted > 0) {
      target.append(node("p", "matrix-note", `${omitted} unavailable candidate${omitted === 1 ? "" : "s"} omitted from the matrix.`));
    }
  }

  function renderTable() {
    const body = document.querySelector("#candidate-table tbody");
    candidates.forEach((candidate) => {
      const row = document.createElement("tr");
      [candidate.player_name, candidate.role_label, formatScore(candidate.fulfillment_score), formatScore(candidate.opportunity_score), formatScore(candidate.stability_score)].forEach((value, index) => {
        const cell = node("td", index > 1 ? "numeric" : null, value);
        row.append(cell);
      });
      const action = document.createElement("td");
      const button = node("button", "table-button", "Open");
      button.type = "button";
      button.dataset.playerId = candidate.player_id;
      action.append(button);
      row.append(action);
      body.append(row);
    });
  }

  const METRIC_LABELS = {
    assists_per_75: "Assists per 75 poss",
    assist_turnover_ratio: "Assist / turnover ratio",
    assignment_confidence: "Role assignment confidence",
    consistency: "Possession-share variability",
    fta_rate: "Free-throw attempt rate",
    games: "Player games",
    minutes_per_game: "Minutes per game",
    offensive_rebounds_per_75_off_poss: "Offensive rebounds per 75 poss",
    possession_share: "Possession share",
    possession_share_delta: "Possession share change",
    possessions: "Offensive possessions",
    rebounds_per_75_total_possessions: "Rebounds per 75 poss",
    rim_fg_pct: "Rim FG%",
    rim_fga_share: "Rim FGA share",
    three_point_fga_share: "3-point FGA share",
    true_shooting_pct: "True shooting %",
    turnover_rate: "Turnover rate",
  };

  function metricLabel(code) {
    return METRIC_LABELS[code] || code.replaceAll("_", " ");
  }

  function contextCard(label, value, note) {
    const card = node("article", "context-card");
    card.append(node("span", null, label));
    card.append(node("strong", null, value));
    if (note) card.append(node("small", null, note));
    return card;
  }

  function formatWindow(start, end) {
    if (!start || !end) return "Unavailable";
    return `${start} → ${end}`;
  }

  function renderWindowContext(candidate) {
    const target = document.getElementById("evidence-window-context");
    const windows = payload.meta.windows || {};
    target.replaceChildren(
      contextCard("Recent window", formatWindow(windows.recent_start, windows.recent_end), "Current role evidence"),
      contextCard("Prior window", formatWindow(windows.baseline_start, windows.baseline_end), "Comparison baseline"),
      contextCard("Season context", `Through ${windows.recent_end || "unavailable"}`, "Regular season to analysis cutoff"),
      contextCard(
        "Position context",
        candidate.position_name || candidate.position_abbreviation || "Unavailable",
        "Benchmarks pending reviewed cohort adapter"
      )
    );
  }

  function sampleValue(label, value) {
    const item = node("span", "sample-value");
    item.append(node("small", null, label), node("b", null, formatMetricValue("possessions", value)));
    return item;
  }

  function sampleWindow(candidate, prefix, title) {
    const group = node("article", "sample-window");
    group.append(node("h4", null, title));
    const values = node("div", "sample-values");
    values.append(
      sampleValue("Team games", candidate[`${prefix}_team_games`]),
      sampleValue("Player games", candidate[`${prefix}_games`]),
      sampleValue("Off poss", candidate[`${prefix}_off_poss`]),
      sampleValue("Team poss in player games", candidate[`${prefix}_team_possessions`])
    );
    group.append(values);
    return group;
  }

  function renderSampleContext(candidate) {
    const target = document.getElementById("evidence-sample-context");
    const heading = node("div", "sample-heading");
    heading.append(node("h3", null, "Sample context"), node("p", null, "Team schedule and player participation remain separate."));
    const windows = node("div", "sample-grid");
    windows.append(
      sampleWindow(candidate, "recent", "Recent"),
      sampleWindow(candidate, "baseline", "Prior"),
      sampleWindow(candidate, "season", "Season")
    );
    target.replaceChildren(heading, windows);
  }

  function evidenceTable(candidate, rows, family) {
    const wrap = node("div", "evidence-table-wrap");
    const table = node("table", "evidence-table");
    const head = document.createElement("thead");
    const headRow = document.createElement("tr");
    [
      "Metric",
      "Recent",
      "Prior window",
      "Season",
      family === "opportunity" ? "Change" : "Position context",
    ].forEach((label) => headRow.append(node("th", null, label)));
    head.append(headRow);
    const body = document.createElement("tbody");
    rows.forEach((item) => {
      const context = buildMetricContext(candidate, item.metric_code);
      const row = document.createElement("tr");
      const metric = node("td", "metric-name");
      metric.append(node("strong", null, metricLabel(item.metric_code)));
      metric.append(node("small", null, `Denominator ${formatEvidenceValue(item.denominator, 1)}`));
      row.append(metric);
      row.append(node("td", "numeric evidence-current", formatMetricValue(item.metric_code, context.recent)));
      row.append(node("td", "numeric", formatMetricValue(item.metric_code, context.baseline)));
      row.append(node("td", "numeric", formatMetricValue(item.metric_code, context.season)));
      if (family === "opportunity") {
        const change = item.metric_code === "possession_share_delta"
          ? formatMetricValue(item.metric_code, context.recent)
          : formatMetricChange(item.metric_code, context.recent, context.baseline);
        row.append(node("td", "numeric evidence-change", change));
      } else if (family === "fulfillment") {
        const pending = node("td", "benchmark-pending", "Pending adapter");
        pending.title = "Position averages and percentiles are suppressed until the benchmark cohort is reviewed.";
        row.append(pending);
      } else {
        row.append(node("td", "benchmark-na", "Not applicable"));
      }
      body.append(row);
    });
    table.append(head, body);
    wrap.append(table);
    return wrap;
  }

  function provenanceDetails(rows) {
    const details = node("details", "provenance-details");
    details.append(node("summary", null, "Method & provenance"));
    const list = node("div", "provenance-list");
    rows.forEach((item) => {
      const line = node("p");
      line.append(node("strong", null, metricLabel(item.metric_code)));
      line.append(node(
        "span",
        null,
        `${item.source_name} · ${item.window_scope} · raw ${formatEvidenceValue(item.metric_value)} · ${item.window_start || "n/a"} to ${item.window_end || "n/a"}`
      ));
      list.append(line);
    });
    details.append(list);
    return details;
  }

  function openEvidence(playerId) {
    const candidate = candidates.find((item) => item.player_id === playerId);
    const rows = evidence.filter((item) => item.player_id === playerId);
    const dialog = document.getElementById("evidence-dialog");
    document.getElementById("evidence-title").textContent = candidate.player_name;
    document.getElementById("evidence-subtitle").textContent = `${candidate.team_abbreviation} · ${candidate.position_name || candidate.position_abbreviation || "Position unavailable"} · ${candidate.role_label} · ${candidate.score_status.replaceAll("_", " ")}`;
    renderWindowContext(candidate);
    renderSampleContext(candidate);
    const content = document.getElementById("evidence-content");
    content.replaceChildren();
    ["fulfillment", "opportunity", "stability"].forEach((family) => {
      const familyRows = rows.filter((item) => item.score_family === family);
      if (!familyRows.length) return;
      const section = node("section", "evidence-family");
      section.append(node("h3", null, family));
      section.append(evidenceTable(candidate, familyRows, family));
      content.append(section);
    });
    content.append(provenanceDetails(rows));
    const safeguard = node(
      "p",
      "safeguard",
      isFixture
        ? "Safeguard: fixture-only; rates recomputed from additive counts. No composite score."
        : (isLive
          ? "Safeguard: reviewed live sources, additive counts, no composite score, and manual execution only."
          : "Safeguard: live dry run only; reviewed sources, additive counts, no composite score, and no publishing.")
    );
    content.append(safeguard);
    dialog.showModal();
  }

  document.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-player-id]");
    if (trigger) openEvidence(trigger.dataset.playerId);
  });
  document.getElementById("close-evidence").addEventListener("click", () => document.getElementById("evidence-dialog").close());
  document.getElementById("formula-version").textContent = payload.meta.formula_version;

  renderFunnel();
  renderCards();
  renderMatrix();
  renderTable();
})();

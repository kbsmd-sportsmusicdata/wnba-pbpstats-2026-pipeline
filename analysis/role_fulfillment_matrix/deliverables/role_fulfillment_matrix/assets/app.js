(() => {
  "use strict";

  const payload = JSON.parse(document.getElementById("rfm-data").textContent);
  const candidates = payload.candidates;
  const evidence = payload.evidence;

  function node(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  function score(value) {
    return Number(value).toFixed(0);
  }

  function renderFunnel() {
    const target = document.getElementById("funnel-summary");
    const counts = payload.meta.funnel_counts;
    const items = [
      ["Roster pool", counts.players_considered],
      ["Contender gate", counts.players_considered - (counts.excluded_non_contender_team || 0)],
      ["Reviewed eligibility", counts.players_considered - (counts.excluded_non_contender_team || 0) - (counts.excluded_eligibility_not_reviewed || 0)],
      ["Scored fixtures", counts.players_scored],
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
    const line = node("div", "metric-line");
    line.append(node("span", null, label));
    line.append(node("b", null, score(value)));
    const track = node("div", "track");
    const fill = node("span", `fill fill-${code}`);
    fill.style.width = `${Math.max(0, Math.min(100, Number(value)))}%`;
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
      top.append(identity, node("span", "fixture-tag", "FIXTURE"));
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

    candidates.forEach((candidate, index) => {
      const x = plot.x + Number(candidate.opportunity_score) / 100 * plot.w;
      const y = plot.y + plot.h - Number(candidate.fulfillment_score) / 100 * plot.h;
      const radius = 10 + Number(candidate.stability_score) / 100 * 12;
      const circle = svgElement("circle", {cx: x, cy: y, r: radius, class: `candidate-dot dot-${index}`});
      circle.setAttribute("tabindex", "0");
      circle.setAttribute("aria-label", `${candidate.player_name}: Fulfillment ${score(candidate.fulfillment_score)}, Opportunity ${score(candidate.opportunity_score)}, Stability ${score(candidate.stability_score)}`);
      circle.dataset.playerId = candidate.player_id;
      svg.append(circle);
      const label = svgElement("text", {x: x + radius + 8, y: y + 5, class: "dot-label"});
      label.textContent = candidate.player_name;
      svg.append(label);
    });
    target.append(svg);
  }

  function renderTable() {
    const body = document.querySelector("#candidate-table tbody");
    candidates.forEach((candidate) => {
      const row = document.createElement("tr");
      [candidate.player_name, candidate.role_label, score(candidate.fulfillment_score), score(candidate.opportunity_score), score(candidate.stability_score)].forEach((value, index) => {
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

  function openEvidence(playerId) {
    const candidate = candidates.find((item) => item.player_id === playerId);
    const rows = evidence.filter((item) => item.player_id === playerId);
    const dialog = document.getElementById("evidence-dialog");
    document.getElementById("evidence-title").textContent = candidate.player_name;
    document.getElementById("evidence-subtitle").textContent = `${candidate.team_abbreviation} · ${candidate.role_label} · ${candidate.score_status.replace("_", " ")}`;
    const content = document.getElementById("evidence-content");
    content.replaceChildren();
    ["fulfillment", "opportunity", "stability"].forEach((family) => {
      const section = node("section", "evidence-family");
      section.append(node("h3", null, family));
      rows.filter((item) => item.score_family === family).forEach((item) => {
        const line = node("div", "evidence-row");
        const copy = node("div");
        copy.append(node("strong", null, item.metric_code.replaceAll("_", " ")));
        copy.append(node("small", null, `Denominator ${Number(item.denominator).toFixed(1)} · ${item.window_start} to ${item.window_end}`));
        line.append(copy, node("b", null, item.metric_value === null ? "Unavailable" : Number(item.metric_value).toFixed(3)));
        section.append(line);
      });
      content.append(section);
    });
    const safeguard = node("p", "safeguard", "Safeguard: fixture-only; rates recomputed from additive counts. No composite score.");
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

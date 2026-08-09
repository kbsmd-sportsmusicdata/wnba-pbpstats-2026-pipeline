(function () {
  "use strict";

  const charts = window.ForecastCharts;
  const config = {
    season: Number(document.documentElement.dataset.season),
    teamCount: Number(document.documentElement.dataset.teamCount),
    qualifiers: Number(document.documentElement.dataset.playoffQualifiers),
    topBoundary: Number(document.documentElement.dataset.topBoundary),
  };
  const allowedRace = new Set(["all", "top4", "cutline", "longshots"]);
  const allowedProbability = new Set(["playoff", "rank", "wins"]);
  const state = { team: "", race: "all", probability: "playoff" };
  let payload = null;

  async function loadForecast() {
    const response = await fetch("./data/forecast_payload.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`Forecast payload failed: ${response.status}`);
    return response.json();
  }

  function byId(id) {
    return document.getElementById(id);
  }

  function formatProbability(value) {
    return value === null || value === undefined ? "Unavailable" : `${(Number(value) * 100).toFixed(1)}%`;
  }

  function formatNumber(value, digits) {
    return value === null || value === undefined || Number.isNaN(Number(value))
      ? "Unavailable"
      : Number(value).toFixed(digits);
  }

  function formatInteger(value) {
    return value === null || value === undefined || Number.isNaN(Number(value))
      ? "Unavailable"
      : String(Math.trunc(Number(value)));
  }

  function formatDate(value) {
    if (!value) return "Unavailable";
    const parsed = new Date(`${String(value).slice(0, 10)}T00:00:00`);
    return Number.isNaN(parsed.valueOf())
      ? String(value)
      : parsed.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  }

  function makeDefinitionList(container, rows) {
    charts.clear(container);
    rows.forEach(([term, description]) => {
      const row = charts.element("div");
      row.appendChild(charts.element("dt", term));
      row.appendChild(charts.element("dd", description));
      container.appendChild(row);
    });
  }

  function forecastRows() {
    return payload.forecast_summary.slice().sort((a, b) => Number(a.current_rank) - Number(b.current_rank) || String(a.team_id).localeCompare(String(b.team_id)));
  }

  function filterRace(rows) {
    if (state.race === "top4") return rows.filter((row) => Number(row.current_rank) <= config.topBoundary);
    if (state.race === "cutline") {
      const low = Math.max(1, config.qualifiers - 2);
      const high = Math.min(config.teamCount, config.qualifiers + 2);
      return rows.filter((row) => Number(row.current_rank) >= low && Number(row.current_rank) <= high);
    }
    if (state.race === "longshots") {
      return rows.filter((row) => Number(row.current_rank) > config.qualifiers && Number(row.playoff_probability) > 0);
    }
    return rows;
  }

  function rowClass(row) {
    const names = [];
    if (Number(row.current_rank) === config.qualifiers) names.push("cutline-row");
    if (String(row.team_id) === state.team) names.push("selected-row");
    return names.join(" ");
  }

  function selectedForecast(rows) {
    return rows.find((row) => String(row.team_id) === state.team) || rows[0];
  }

  function updateTeamOptions(rows) {
    const select = byId("team-select");
    const visibleIds = new Set(rows.map((row) => String(row.team_id)));
    if (!visibleIds.has(state.team) && rows.length) state.team = String(rows[0].team_id);
    charts.clear(select);
    rows.forEach((row) => {
      const option = charts.element("option", row.team_abbreviation);
      option.value = String(row.team_id);
      option.selected = option.value === state.team;
      select.appendChild(option);
    });
    select.disabled = rows.length === 0;
  }

  function renderKpis(rows) {
    const leader = rows[0];
    const cutline = rows.find((row) => Number(row.current_rank) === config.qualifiers);
    const firstOut = rows.find((row) => Number(row.current_rank) === config.qualifiers + 1);
    const leverage = payload.leverage_games.slice().sort((a, b) => Number(b.leverage_score) - Number(a.leverage_score) || String(a.game_id).localeCompare(String(b.game_id)))[0];
    makeDefinitionList(byId("kpi-list"), [
      ["Configured playoff field", `${config.qualifiers} of ${config.teamCount}`],
      ["Current leader", leader ? `${leader.team_abbreviation} · ${formatProbability(leader.playoff_probability)}` : "Unavailable"],
      ["Cutline qualifier", cutline ? `${cutline.team_abbreviation} · ${formatProbability(cutline.playoff_probability)}` : "Unavailable"],
      ["First out", firstOut ? `${firstOut.team_abbreviation} · ${formatProbability(firstOut.playoff_probability)}` : "Unavailable"],
      ["Highest leverage", leverage ? `${leverage.game_id} · ${formatNumber(leverage.leverage_score, 1)}` : "No remaining games"],
    ]);
  }

  function renderCurrent(rows) {
    const currentByTeam = new Map(payload.standings.map((row) => [String(row.team_id), row]));
    charts.renderTable(
      byId("current-table"),
      "Current official order from the supplied forecast bundle",
      [
        { label: "Rank", value: (row) => formatInteger(row.current_rank) },
        { label: "Team", value: (row) => row.team_abbreviation },
        { label: "W", value: (row) => formatInteger(currentByTeam.get(String(row.team_id)).wins) },
        { label: "L", value: (row) => formatInteger(currentByTeam.get(String(row.team_id)).losses) },
        { label: "Pct", value: (row) => formatProbability(currentByTeam.get(String(row.team_id)).win_pct) },
        { label: "Point diff", value: (row) => formatNumber(currentByTeam.get(String(row.team_id)).point_differential, 1) },
        { label: "Playoff", value: (row) => charts.probabilityBar(row.playoff_probability, formatProbability(row.playoff_probability)) },
      ],
      rows,
      rowClass
    );
  }

  function renderProjected(rows) {
    const ordered = rows.slice().sort((a, b) => Number(b.projected_wins_mean) - Number(a.projected_wins_mean) || String(a.team_id).localeCompare(String(b.team_id)));
    let evidence;
    let note;
    if (state.probability === "rank") {
      evidence = { label: "Expected rank", value: (row) => formatNumber(row.expected_final_rank, 2) };
      note = "Primary evidence: supplied expected final rank; the exact-rank matrix remains visible below.";
    } else if (state.probability === "wins") {
      evidence = { label: "Wins P10 · P50 · P90", value: (row) => `${formatNumber(row.wins_p10, 1)} · ${formatNumber(row.wins_p50, 1)} · ${formatNumber(row.wins_p90, 1)}` };
      note = "Primary evidence: supplied projected-wins uncertainty range.";
    } else {
      evidence = { label: "Playoff", value: (row) => charts.probabilityBar(row.playoff_probability, formatProbability(row.playoff_probability)) };
      note = "Primary evidence: supplied playoff probability.";
    }
    byId("probability-mode-note").textContent = note;
    charts.renderTable(
      byId("projected-table"),
      "Projected order and supplied probability evidence",
      [
        { label: "Team", value: (row) => row.team_abbreviation },
        { label: "Projected wins", value: (row) => formatNumber(row.projected_wins_mean, 1) },
        evidence,
      ],
      ordered,
      rowClass
    );
  }

  function renderLeverage() {
    const abbreviations = new Map(payload.forecast_summary.map((row) => [String(row.team_id), row.team_abbreviation]));
    const rows = payload.leverage_games.slice().sort((a, b) => Number(b.leverage_score) - Number(a.leverage_score) || String(a.game_id).localeCompare(String(b.game_id)));
    if (!rows.length) {
      charts.clear(byId("leverage-table"));
      byId("leverage-table").appendChild(charts.element("p", "No remaining games; leverage and conditional branches are not applicable.", "empty-state"));
      return;
    }
    charts.renderTable(
      byId("leverage-table"),
      "Supplied remaining-game leverage and conditional swings",
      [
        { label: "Date", value: (row) => formatDate(row.game_date) },
        { label: "Matchup", value: (row) => `${abbreviations.get(String(row.away_id))} at ${abbreviations.get(String(row.home_id))}` },
        { label: "Leverage", value: (row) => `${formatNumber(row.leverage_score, 1)} · ${row.leverage_label}` },
        { label: "Home playoff swing", value: (row) => row.conditional_estimate_available === true ? formatProbability(row.home_playoff_probability_swing) : "Conditional estimate unavailable" },
        { label: "Away playoff swing", value: (row) => row.conditional_estimate_available === true ? formatProbability(row.away_playoff_probability_swing) : "Conditional estimate unavailable" },
      ],
      rows
    );
  }

  function renderTeamDetail(rows) {
    const team = selectedForecast(rows);
    byId("team-title").textContent = team ? `Team detail · ${team.team_abbreviation}` : "Team detail";
    if (!team) {
      makeDefinitionList(byId("team-detail-list"), [["Status", "No team is visible in this race view"]]);
      return;
    }
    makeDefinitionList(byId("team-detail-list"), [
      ["Current record", `${formatInteger(team.current_wins)}–${formatInteger(team.current_losses)}`],
      ["Playoff probability", formatProbability(team.playoff_probability)],
      ["Top 4 / home court", formatProbability(team.home_court_probability)],
      ["Expected final rank", formatNumber(team.expected_final_rank, 2)],
      ["Projected wins", formatNumber(team.projected_wins_mean, 1)],
      ["Wins P10 · P50 · P90", `${formatNumber(team.wins_p10, 1)} · ${formatNumber(team.wins_p50, 1)} · ${formatNumber(team.wins_p90, 1)}`],
      ["Remaining SOS rank", formatInteger(team.remaining_sos_rank)],
      ["Mathematical status", team.status_note === "not_evaluated" ? "Status not evaluated" : String(team.status_note || "Status not evaluated")],
    ]);
  }

  function renderHistory() {
    const container = byId("history-content");
    charts.clear(container);
    const available = payload.historical_context.filter((row) => row.availability_status === "available");
    if (!available.length) {
      container.appendChild(charts.element("p", "Historical context unavailable for this run; no comparison is inferred.", "empty-state"));
      return;
    }
    charts.renderTable(
      container,
      "Available supplied historical benchmarks",
      [
        { label: "Season", value: (row) => row.season },
        { label: "Metric", value: (row) => String(row.metric).replaceAll("_", " ") },
        { label: "Value", value: (row) => formatNumber(row.value, 2) },
        { label: "Sample", value: (row) => formatInteger(row.sample_size) },
      ],
      available
    );
  }

  function renderInsights() {
    const list = byId("insights-list");
    charts.clear(list);
    payload.broadcast_insights.slice().sort((a, b) => Number(a.priority) - Number(b.priority)).forEach((insight) => {
      const item = charts.element("li");
      const heading = charts.element("strong", `${insight.priority}. ${String(insight.category).replaceAll("_", " ")}: `);
      item.appendChild(heading);
      item.appendChild(document.createTextNode(String(insight.quick_read_snippet)));
      list.appendChild(item);
    });
  }

  function renderMethod() {
    const metadata = payload.metadata;
    makeDefinitionList(byId("method-list"), [
      ["Cutoff", metadata.cutoff_date],
      ["Model", metadata.model_version],
      ["Runs", Number(metadata.simulation_count).toLocaleString()],
      ["Seed", String(metadata.random_seed)],
      ["PBPStats", metadata.pbpstats_enrichment_status],
      ["History seasons", metadata.history_seasons_used.length ? metadata.history_seasons_used.join(", ") : "Unavailable"],
    ]);
  }

  function updateUrl(mode) {
    const query = new URLSearchParams();
    if (state.team) query.set("team", state.team);
    query.set("race", state.race);
    query.set("probability", state.probability);
    const next = `${window.location.pathname}?${query.toString()}${window.location.hash}`;
    if (mode === "push") window.history.pushState({ ...state }, "", next);
    else if (mode === "replace") window.history.replaceState({ ...state }, "", next);
  }

  function restoreStateFromUrl() {
    const query = new URLSearchParams(window.location.search);
    const race = query.get("race");
    const probability = query.get("probability");
    if (allowedRace.has(race)) state.race = race;
    if (allowedProbability.has(probability)) state.probability = probability;
    state.team = query.get("team") || state.team;
    document.querySelectorAll('input[name="race"]').forEach((control) => { control.checked = control.value === state.race; });
    document.querySelectorAll('input[name="probability"]').forEach((control) => { control.checked = control.value === state.probability; });
  }

  function render(historyMode) {
    const allRows = forecastRows();
    const visibleRows = filterRace(allRows);
    updateTeamOptions(visibleRows);
    renderKpis(allRows);
    renderCurrent(visibleRows);
    renderProjected(visibleRows);
    charts.renderHeatmap(byId("rank-table"), visibleRows, payload.rank_probability_matrix, config.teamCount, formatProbability);
    renderLeverage();
    renderTeamDetail(visibleRows);
    renderHistory();
    renderInsights();
    renderMethod();
    updateUrl(historyMode);
    byId("app-status").textContent = `${visibleRows.length} of ${config.teamCount} teams shown · ${state.race} race · ${state.probability} probability evidence.`;
  }

  function bindControls() {
    byId("team-select").addEventListener("change", (event) => { state.team = event.target.value; render("push"); });
    document.querySelectorAll('input[name="race"]').forEach((control) => {
      control.addEventListener("change", (event) => { state.race = event.target.value; render("push"); });
    });
    document.querySelectorAll('input[name="probability"]').forEach((control) => {
      control.addEventListener("change", (event) => { state.probability = event.target.value; render("push"); });
    });
    window.addEventListener("popstate", () => { restoreStateFromUrl(); render("none"); });
  }

  function showError(error) {
    const errorState = byId("error-state");
    errorState.hidden = false;
    errorState.textContent = `Forecast unavailable. ${error.message}. Confirm the published data/forecast_payload.json file is present and valid.`;
    byId("app-status").textContent = "Forecast payload could not be loaded.";
    byId("main-content").classList.add("has-error");
  }

  async function start() {
    try {
      payload = await loadForecast();
      restoreStateFromUrl();
      const rows = forecastRows();
      if (!state.team && rows.length) state.team = String(rows[0].team_id);
      byId("header-cutoff").textContent = payload.metadata.cutoff_date;
      byId("header-model").textContent = payload.metadata.model_version;
      byId("header-status").textContent = `Season ${config.season} · supplied forecast through ${payload.metadata.cutoff_date}`;
      bindControls();
      render("replace");
    } catch (error) {
      showError(error instanceof Error ? error : new Error(String(error)));
    }
  }

  window.addEventListener("DOMContentLoaded", start);
})();

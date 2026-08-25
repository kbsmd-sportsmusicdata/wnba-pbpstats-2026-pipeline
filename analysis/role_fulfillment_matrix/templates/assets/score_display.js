(function exposeScoreDisplay(root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.RFMScoreDisplay = api;
})(typeof globalThis !== "undefined" ? globalThis : this, () => {
  "use strict";

  function isFiniteScore(value) {
    return typeof value === "number" && Number.isFinite(value);
  }

  function formatScore(value) {
    return isFiniteScore(value) ? value.toFixed(0) : "Unavailable";
  }

  function scoreWidth(value) {
    return isFiniteScore(value) ? Math.max(0, Math.min(100, value)) : 0;
  }

  function hasPlottableScores(candidate) {
    return candidate.score_status !== "unavailable"
      && isFiniteScore(candidate.fulfillment_score)
      && isFiniteScore(candidate.opportunity_score)
      && isFiniteScore(candidate.stability_score);
  }

  function formatEvidenceValue(value, digits = 3) {
    return isFiniteScore(value) ? value.toFixed(digits) : "Unavailable";
  }

  const PERCENT_METRICS = new Set([
    "assignment_confidence",
    "consistency",
    "fta_rate",
    "possession_share",
    "rim_fg_pct",
    "rim_fga_share",
    "three_point_fga_share",
    "true_shooting_pct",
    "turnover_rate",
  ]);

  function formatMetricValue(code, value) {
    if (!isFiniteScore(value)) return "—";
    if (code === "possession_share_delta") {
      const sign = value > 0 ? "+" : "";
      return `${sign}${(value * 100).toFixed(1)} pp`;
    }
    if (PERCENT_METRICS.has(code)) return `${(value * 100).toFixed(1)}%`;
    if (code === "games" || code === "possessions") return value.toFixed(0);
    return value.toFixed(1);
  }

  function contextKey(code) {
    if (code === "games") return "games";
    if (code === "possessions") return "off_poss";
    if (code === "consistency") return "possession_share_sd";
    return code;
  }

  function buildMetricContext(candidate, code) {
    if (code === "assignment_confidence") {
      return {recent: candidate.assignment_confidence, baseline: null, season: null};
    }
    if (code === "possession_share_delta") {
      const recent = candidate.recent_possession_share;
      const baseline = candidate.baseline_possession_share;
      const delta = isFiniteScore(recent) && isFiniteScore(baseline)
        ? Number((recent - baseline).toFixed(12))
        : null;
      return {recent: delta, baseline: null, season: null};
    }
    const key = contextKey(code);
    return {
      recent: candidate[`recent_${key}`],
      baseline: candidate[`baseline_${key}`],
      season: candidate[`season_${key}`],
    };
  }

  function formatMetricChange(code, recent, baseline) {
    if (!isFiniteScore(recent) || !isFiniteScore(baseline)) return "—";
    const delta = recent - baseline;
    if (PERCENT_METRICS.has(code)) return formatMetricValue("possession_share_delta", delta);
    const sign = delta > 0 ? "+" : "";
    return `${sign}${delta.toFixed(1)}`;
  }

  return {
    buildMetricContext,
    formatEvidenceValue,
    formatMetricChange,
    formatMetricValue,
    formatScore,
    hasPlottableScores,
    scoreWidth,
  };
});

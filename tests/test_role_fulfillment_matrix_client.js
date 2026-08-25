const test = require("node:test");
const assert = require("node:assert/strict");

const {
  buildMetricContext,
  buildMetricDenominators,
  formatEvidenceValue,
  formatMetricChange,
  formatMetricValue,
  formatScore,
  hasPlottableScores,
  scoreWidth,
} = require("../analysis/role_fulfillment_matrix/templates/assets/score_display.js");


test("unavailable scores remain unavailable instead of coercing to zero", () => {
  assert.equal(formatScore(null), "Unavailable");
  assert.equal(formatScore(undefined), "Unavailable");
  assert.equal(formatScore(Number.NaN), "Unavailable");
  assert.equal(scoreWidth(null), 0);
});


test("the matrix omits candidates without all three available scores", () => {
  assert.equal(hasPlottableScores({
    score_status: "unavailable",
    fulfillment_score: null,
    opportunity_score: 70,
    stability_score: 80,
  }), false);
  assert.equal(hasPlottableScores({
    score_status: "fixture_only",
    fulfillment_score: 60,
    opportunity_score: 70,
    stability_score: 80,
  }), true);
});


test("evidence nulls remain unavailable", () => {
  assert.equal(formatEvidenceValue(null), "Unavailable");
  assert.equal(formatEvidenceValue(3), "3.000");
});


test("drawer values use basketball-readable units without changing raw data", () => {
  assert.equal(formatMetricValue("true_shooting_pct", 0.625), "62.5%");
  assert.equal(formatMetricValue("minutes_per_game", 30.264), "30.3");
  assert.equal(formatMetricValue("offensive_rebounds_per_75_off_poss", 5.569), "5.6");
  assert.equal(formatMetricValue("games", 6), "6");
  assert.equal(formatMetricValue("possession_share_delta", 0.121), "+12.1 pp");
});


test("metric context reads recent prior and season fields without calculating new scores", () => {
  const candidate = {
    recent_true_shooting_pct: 0.625,
    baseline_true_shooting_pct: 0.588,
    season_true_shooting_pct: 0.603,
    recent_possession_share: 0.737,
    baseline_possession_share: 0.616,
    season_possession_share: 0.681,
  };
  assert.deepEqual(buildMetricContext(candidate, "true_shooting_pct"), {
    recent: 0.625,
    baseline: 0.588,
    season: 0.603,
  });
  assert.deepEqual(buildMetricContext(candidate, "possession_share_delta"), {
    recent: 0.737,
    baseline: 0.616,
    season: 0.681,
  });
  assert.equal(
    formatMetricChange("possession_share", 0.737, 0.616),
    "+12.1 pp",
  );
});


test("each comparison window receives its own metric denominator", () => {
  const candidate = {
    recent_off_poss: 120,
    baseline_off_poss: 90,
    season_off_poss: 210,
    recent_true_shooting_attempts: 28.96,
    baseline_true_shooting_attempts: 26.64,
    season_true_shooting_attempts: 55.6,
  };
  assert.deepEqual(buildMetricDenominators(candidate, "assists_per_75"), {
    recent: 120,
    baseline: 90,
    season: 210,
  });
  assert.deepEqual(buildMetricDenominators(candidate, "true_shooting_pct"), {
    recent: 28.96,
    baseline: 26.64,
    season: 55.6,
  });
});

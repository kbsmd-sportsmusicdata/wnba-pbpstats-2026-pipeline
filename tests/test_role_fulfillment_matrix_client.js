const test = require("node:test");
const assert = require("node:assert/strict");

const {
  buildMetricContext,
  formatEvidenceValue,
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
  };
  assert.deepEqual(buildMetricContext(candidate, "true_shooting_pct"), {
    recent: 0.625,
    baseline: 0.588,
    season: 0.603,
  });
  assert.deepEqual(buildMetricContext(candidate, "possession_share_delta"), {
    recent: 0.121,
    baseline: null,
    season: null,
  });
});

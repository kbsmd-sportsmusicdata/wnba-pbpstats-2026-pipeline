const test = require("node:test");
const assert = require("node:assert/strict");

const {
  formatEvidenceValue,
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

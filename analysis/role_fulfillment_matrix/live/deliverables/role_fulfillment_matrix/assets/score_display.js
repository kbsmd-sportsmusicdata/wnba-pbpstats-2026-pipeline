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

  return {formatEvidenceValue, formatScore, hasPlottableScores, scoreWidth};
});

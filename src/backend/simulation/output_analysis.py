"""Output analysis for port_typhoon_simulator DES replications.

Implements the statistical comparison protocol:
  - CI half-width for throughput mean (t-interval)
  - Cohen's dz for paired data (same RNG seed pairing via CRN)
  - Paired t-test for baseline vs scenario throughput
  - operationally_meaningful flag (dual threshold: ≥5% loss AND |dz|≥0.2)

All functions are pure (no SimPy, no randomness) → unit-testable.
"""

from __future__ import annotations

import numpy as np
from scipy import stats as sp_stats

# ---------------------------------------------------------------------------
# Step 1 — Normality check (Shapiro-Wilk)
# ---------------------------------------------------------------------------

def check_normality(results: list[float], alpha: float = 0.05) -> dict:
    """Shapiro-Wilk normality test (Step 1: normality check).

    Note: for n > 50, SW is sensitive to minor deviations; p < alpha does NOT
    automatically require switching CI method — CLT applies (see choose_ci_method).
    """
    stat, p = sp_stats.shapiro(results)
    normal = bool(p > alpha)
    return {
        "stat":      float(stat),
        "p_value":   float(p),
        "is_normal": normal,
        "action":    "use t-CI" if normal else "→ Step 1.5: run choose_ci_method()",
    }


# ---------------------------------------------------------------------------
# Step 1.5 — CI method selection
# ---------------------------------------------------------------------------

def choose_ci_method(results: list[float], n_threshold: int = 50) -> str:
    """Select CI method based on data characteristics (Step 1.5: CI method selection).

    Priority (high → low):
      1. data spans ≥ 2 orders of magnitude → log-transform-CI
      2. n ≤ n_threshold AND skewness > 1.0  → bootstrap-CI
      3. n > n_threshold                     → t-CI (CLT; non-normal warning)
      4. else                                → bootstrap-CI (conservative)
    """
    data = np.asarray(results, dtype=float)
    log_range = float(np.log10(data.max() / data.min())) if data.min() > 0 else float("inf")

    if log_range > 2:
        return "log-transform-CI"
    if len(data) <= n_threshold and float(sp_stats.skew(data)) > 1.0:
        return "bootstrap-CI"
    if len(data) > n_threshold:
        return "t-CI (CLT; non-normal warning)"
    return "bootstrap-CI"


def bootstrap_ci(
    results: list[float],
    alpha: float = 0.05,
    n_boot: int = 10_000,
    seed: int = 42,
) -> dict:
    """Percentile bootstrap CI for the mean (Step 1.5: CI method selection).

    Fixed seed ensures reproducibility across runs.
    """
    rng = np.random.default_rng(seed)
    data = np.asarray(results, dtype=float)
    boot_means = np.array([
        rng.choice(data, size=len(data), replace=True).mean()
        for _ in range(n_boot)
    ])
    lo = float(np.percentile(boot_means, 100 * alpha / 2))
    hi = float(np.percentile(boot_means, 100 * (1 - alpha / 2)))
    mean = float(data.mean())
    return {
        "mean":         mean,
        "ci_lower":     lo,
        "ci_upper":     hi,
        "ci_half_width": (hi - lo) / 2.0,
        "method":       f"bootstrap-CI (percentile, n_boot={n_boot})",
    }


def log_transform_ci(results: list[float], alpha: float = 0.05) -> dict:
    """CI on log-scale, back-transformed (Step 1.5: CI method selection).

    Use when data spans ≥ 2 orders of magnitude.
    Reports geometric mean; arithmetic mean = exp(mean_log + std_log²/2).
    """
    data = np.asarray(results, dtype=float)
    if np.any(data <= 0):
        raise ValueError("log_transform_ci requires all values > 0")
    log_data = np.log(data)
    n = len(log_data)
    mean_log = float(log_data.mean())
    std_log = float(log_data.std(ddof=1))
    t_crit = sp_stats.t.ppf(1 - alpha / 2, df=n - 1)
    margin = t_crit * std_log / np.sqrt(n)
    geo_mean = float(np.exp(mean_log))
    arith_mean = float(np.exp(mean_log + std_log ** 2 / 2))
    hw = (np.exp(mean_log + margin) - np.exp(mean_log - margin)) / 2.0
    return {
        "geometric_mean":  geo_mean,
        "arithmetic_mean": arith_mean,
        "ci_lower":        float(np.exp(mean_log - margin)),
        "ci_upper":        float(np.exp(mean_log + margin)),
        "ci_half_width":   float(hw),
        "method":          "log-transform-CI (back-transformed)",
    }


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

def compute_ci_half_width(values: list[float], confidence: float = 0.95) -> float:
    """Half-width of two-sided t-interval for the mean of `values`.

    Returns 0.0 when all values are identical (zero variance).
    """
    arr = np.asarray(values, dtype=float)
    n = len(arr)
    if n < 2:
        return 0.0
    se = arr.std(ddof=1) / np.sqrt(n)
    if se == 0.0:
        return 0.0
    t_crit = sp_stats.t.ppf((1.0 + confidence) / 2.0, df=n - 1)
    return float(t_crit * se)


def cohens_dz(
    baseline: list[float],
    scenario: list[float],
) -> float:
    """Cohen's dz for paired observations (CRN-paired replications).

    dz = mean(baseline - scenario) / std(baseline - scenario)

    Positive dz → baseline > scenario (scenario has lower throughput).
    Returns 0.0 if std of differences is zero (identical outputs).
    """
    diffs = np.asarray(baseline, dtype=float) - np.asarray(scenario, dtype=float)
    std_d = diffs.std(ddof=1)
    if std_d == 0.0:
        return 0.0
    return float(diffs.mean() / std_d)


# ---------------------------------------------------------------------------
# Per-scenario summary (for building SimRunResult)
# ---------------------------------------------------------------------------

def compute_scenario_stats(
    throughputs: list[float],
    served_calls: list[float],
    disruption_hrs: list[float],
    confidence: float = 0.95,
) -> dict:
    """Compute summary statistics across all replications for one scenario.

    Runs normality check (Step 1) and CI method selection (Step 1.5) on throughputs.
    CI half-width always uses t-CI (appropriate for n≥50 via CLT); chosen ci_method
    is recorded for audit even when CLT overrides bootstrap/log-transform.

    Returns:
        mean_teu              float  — mean throughput (TEU/year)
        ci_half_width_teu     float  — half-width of t-interval at `confidence`
        served_calls_mean     float  — mean completed vessel calls
        disruption_days_mean  float  — mean disruption duration in days (0 for intact)
        normality_p_value     float  — Shapiro-Wilk p-value for throughput distribution
        is_normal             bool   — normality at alpha=0.05
        ci_method             str    — CI method chosen by choose_ci_method() (Step 1.5)
    """
    normality = check_normality(throughputs)
    ci_method = "t-CI" if normality["is_normal"] else choose_ci_method(throughputs)

    return {
        "mean_teu":             float(np.mean(throughputs)),
        "ci_half_width_teu":    compute_ci_half_width(throughputs, confidence),
        "served_calls_mean":    float(np.mean(served_calls)),
        "disruption_days_mean": float(np.mean(disruption_hrs)) / 24.0,
        "normality_p_value":    normality["p_value"],
        "is_normal":            normality["is_normal"],
        "ci_method":            ci_method,
    }


# ---------------------------------------------------------------------------
# Paired comparison protocol
# ---------------------------------------------------------------------------

def paired_comparison(
    baseline: list[float],
    scenario: list[float],
    alpha: float = 0.05,
    threshold_pct: float = 5.0,
    threshold_dz: float = 0.2,
) -> dict[str, float | bool]:
    """Paired t-test + effect size for baseline vs one disrupted scenario.

    CRN pairing: baseline[i] and scenario[i] share the same RNG seed (rep i),
    so paired t-test on differences is appropriate.

    Args:
        baseline:      per-rep throughputs for intact scenario
        scenario:      per-rep throughputs for disrupted scenario
        alpha:         significance level (default 0.05)
        threshold_pct: minimum % throughput loss to be operationally meaningful
        threshold_dz:  minimum |Cohen's dz| to be operationally meaningful

    Returns dict with:
        mean_loss_teu:           mean(baseline) - mean(scenario)
        relative_diff_pct:       mean_loss_teu / mean(baseline) × 100
        ci_half_width_loss_teu:  half-width of CI for mean loss
        t_statistic:             paired t-statistic
        p_value:                 two-sided p-value
        dz:                      Cohen's dz
        is_significant:          p_value < alpha (statistical)
        operationally_meaningful: relative_diff_pct >= threshold_pct AND |dz| >= threshold_dz
    """
    diffs = np.asarray(baseline, dtype=float) - np.asarray(scenario, dtype=float)
    mean_baseline = float(np.mean(baseline))
    mean_loss = float(diffs.mean())
    rel_pct = (mean_loss / mean_baseline * 100.0) if mean_baseline > 0 else 0.0

    t_stat, p_val = sp_stats.ttest_1samp(diffs, popmean=0.0)
    # Guard: diffs with zero variance → ttest produces NaN; no evidence of effect
    if np.isnan(p_val) or np.isnan(t_stat):
        t_stat, p_val = 0.0, 1.0
    dz = cohens_dz(baseline, scenario)
    ci_hw = compute_ci_half_width(list(diffs))

    significant = bool(float(p_val) < alpha)
    meaningful = bool(rel_pct >= threshold_pct and abs(dz) >= threshold_dz)

    return {
        "mean_loss_teu": mean_loss,
        "relative_diff_pct": rel_pct,
        "ci_half_width_loss_teu": ci_hw,
        "t_statistic": float(t_stat),
        "p_value": float(p_val),
        "dz": dz,
        "is_significant": significant,
        "operationally_meaningful": meaningful,
    }


# ---------------------------------------------------------------------------
# Multi-scenario comparison (all 25 scenarios vs baseline)
# ---------------------------------------------------------------------------

def _holm_reject(p_values: list[float], alpha: float) -> list[bool]:
    """Holm-Bonferroni step-down correction for FWER control.

    Orders p-values smallest-first; rejects H_(k) if p_(k) < alpha/(m-k+1).
    Stops at first non-rejection (all remaining are retained).
    """
    m = len(p_values)
    order = sorted(range(m), key=lambda i: p_values[i])
    reject = [False] * m
    for rank, idx in enumerate(order):
        if p_values[idx] < alpha / (m - rank):
            reject[idx] = True
        else:
            break
    return reject


def _decision_signal(*, significant: bool, operationally_meaningful: bool) -> str:
    if significant and operationally_meaningful:
        return "DIFFERENT_AND_MEANINGFUL"
    if significant and not operationally_meaningful:
        return "STAT_SIGNIFICANT_BUT_PRACTICALLY_NEGLIGIBLE"
    return "NOT_SIGNIFICANT"


def multi_scenario_comparison(
    baseline: list[float],
    scenarios: dict[int, list[float]],
    alpha: float = 0.05,
    threshold_pct: float = 5.0,
    threshold_dz: float = 0.2,
) -> dict[int, dict[str, float | bool | str]]:
    """Run paired_comparison for each scenario; apply Holm-Bonferroni correction.

    Holm correction controls FWER across all m comparisons.

    Output fields per scenario:
        p_value             raw paired t-test p-value (uncorrected, for audit)
        is_significant_raw  p_value < alpha before Holm (retained for comparison)
        is_significant      Holm-corrected rejection decision (authoritative)
        is_significant_holm explicit alias of is_significant (CSV readability)
        correction_method   "holm-bonferroni"
        decision_signal     three-way label recomputed from Holm is_significant
        operationally_meaningful  dual threshold (pct + dz) both met
    """
    sids = sorted(scenarios.keys())
    results = {
        sid: paired_comparison(baseline, scenarios[sid], alpha, threshold_pct, threshold_dz)
        for sid in sids
    }

    p_values = [results[sid]["p_value"] for sid in sids]
    reject = _holm_reject(p_values, alpha)

    # decision_signal must be recomputed after Holm — paired_comparison() sets it
    # from raw p < alpha, which is incorrect once Holm correction is applied.
    for sid, rej in zip(sids, reject, strict=False):
        results[sid]["is_significant_raw"] = results[sid]["is_significant"]
        results[sid]["is_significant"]      = bool(rej)
        results[sid]["is_significant_holm"] = bool(rej)
        results[sid]["correction_method"]   = "holm-bonferroni"
        results[sid]["decision_signal"]     = _decision_signal(
            significant=bool(rej),
            operationally_meaningful=bool(results[sid]["operationally_meaningful"]),
        )

    return results

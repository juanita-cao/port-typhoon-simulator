"""Unit tests for output_analysis.py.

All functions are pure numerical → given known inputs, outputs are deterministic.
No SimPy, no RNG — straightforward value-based assertions.
"""

import sys

import numpy as np

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parents[1] / "src"))

from backend.simulation.output_analysis import (
    cohens_dz,
    compute_ci_half_width,
    compute_scenario_stats,
    multi_scenario_comparison,
    paired_comparison,
)

# ---------------------------------------------------------------------------
# compute_ci_half_width
# ---------------------------------------------------------------------------

def test_ci_half_width_zero_variance():
    assert compute_ci_half_width([5.0] * 20) == 0.0


def test_ci_half_width_positive():
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    hw = compute_ci_half_width(values)
    assert hw > 0


def test_ci_half_width_wider_at_lower_confidence():
    values = list(range(1, 21))
    hw95 = compute_ci_half_width(values, confidence=0.95)
    hw80 = compute_ci_half_width(values, confidence=0.80)
    assert hw95 > hw80


def test_ci_half_width_single_value():
    # n < 2 → returns 0 (can't compute interval)
    assert compute_ci_half_width([42.0]) == 0.0


def test_ci_half_width_known_value():
    # n=2, values=[0, 2]: mean=1, std=sqrt(2), se=1, t_{1,0.975}≈12.706 → hw≈12.706
    hw = compute_ci_half_width([0.0, 2.0], confidence=0.95)
    assert abs(hw - 12.706) < 0.01


def test_ci_half_width_larger_n_narrower():
    rng = np.random.default_rng(0)
    small = list(rng.normal(0, 1, 10))
    large = small + list(rng.normal(0, 1, 90))
    # Same underlying distribution, larger sample → narrower interval
    hw_small = compute_ci_half_width(small)
    hw_large = compute_ci_half_width(large)
    assert hw_large < hw_small


# ---------------------------------------------------------------------------
# cohens_dz
# ---------------------------------------------------------------------------

def test_cohens_dz_identical_zero():
    vals = [1.0, 2.0, 3.0, 4.0]
    assert cohens_dz(vals, vals) == 0.0


def test_cohens_dz_positive_when_baseline_higher():
    # Need variance in diffs — use different-scale noise so diffs are not constant
    rng = np.random.default_rng(7)
    noise = rng.normal(0, 1, 20)
    b = [10.0 + x for x in noise]
    s = [8.0 + x * 1.1 for x in noise]   # different noise scale → diffs have variance
    assert cohens_dz(b, s) > 0


def test_cohens_dz_sign_reverses():
    rng = np.random.default_rng(7)
    noise = rng.normal(0, 1, 20)
    b = [10.0 + x for x in noise]
    s = [8.0 + x * 1.1 for x in noise]
    assert cohens_dz(b, s) > 0
    assert cohens_dz(s, b) < 0


def test_cohens_dz_large_systematic_diff():
    # baseline much higher → large dz
    rng = np.random.default_rng(1)
    b = list(rng.normal(100, 2, 50))
    s = list(rng.normal(50, 2, 50))
    dz = cohens_dz(b, s)
    assert dz > 5.0  # huge effect


def test_cohens_dz_zero_std_returns_zero():
    # All diffs equal → std=0 → guard returns 0
    b = [5.0, 6.0, 7.0]
    s = [3.0, 4.0, 5.0]  # diffs all 2.0
    assert cohens_dz(b, s) == 0.0


# ---------------------------------------------------------------------------
# compute_scenario_stats
# ---------------------------------------------------------------------------

def test_scenario_stats_keys():
    out = compute_scenario_stats([1.0, 2.0, 3.0], [100.0, 110.0, 90.0], [0.0, 0.0, 0.0])
    assert "mean_teu" in out
    assert "ci_half_width_teu" in out
    assert "served_calls_mean" in out
    assert "disruption_days_mean" in out


def test_scenario_stats_mean_correct():
    out = compute_scenario_stats([10.0, 20.0, 30.0], [1.0, 1.0, 1.0], [0.0, 0.0, 0.0])
    assert abs(out["mean_teu"] - 20.0) < 1e-9


def test_scenario_stats_served_mean_correct():
    out = compute_scenario_stats([1.0], [5.0, 7.0, 9.0], [0.0])
    assert abs(out["served_calls_mean"] - 7.0) < 1e-9


def test_scenario_stats_disruption_days_zero_for_intact():
    out = compute_scenario_stats([1e7], [4000.0], [0.0])
    assert out["disruption_days_mean"] == 0.0


def test_scenario_stats_disruption_days_conversion():
    # disruption_hrs = 240 → days = 10
    out = compute_scenario_stats([1e7], [4000.0], [240.0])
    assert abs(out["disruption_days_mean"] - 10.0) < 1e-9


def test_scenario_stats_ci_positive_for_varied_data():
    out = compute_scenario_stats([1e7, 1.1e7, 0.9e7], [4000.0], [0.0])
    assert out["ci_half_width_teu"] > 0


# ---------------------------------------------------------------------------
# paired_comparison
# ---------------------------------------------------------------------------

def _make_paired(n=50, baseline_mean=10_000_000, loss_mean=0, noise_std=200_000):
    rng = np.random.default_rng(42)
    noise = rng.normal(0, noise_std, n)
    # Small independent noise on diffs simulates realistic (imperfect) CRN pairing
    diff_noise = rng.normal(0, noise_std * 0.1, n)
    b = list(baseline_mean + noise)
    s = list(baseline_mean - loss_mean + noise + diff_noise)
    return b, s


def test_paired_comparison_keys():
    b, s = _make_paired()
    out = paired_comparison(b, s)
    for key in ["mean_loss_teu", "relative_diff_pct", "ci_half_width_loss_teu",
                "t_statistic", "p_value", "dz", "is_significant", "operationally_meaningful"]:
        assert key in out, f"missing key: {key}"


def test_paired_comparison_identical_not_significant():
    b = [1e7] * 30 + [1.1e7] * 10
    out = paired_comparison(b, b)
    assert out["p_value"] > 0.05
    assert not out["is_significant"]
    assert not out["operationally_meaningful"]


def test_paired_comparison_large_loss_significant():
    # 30% throughput loss with CRN
    b, s = _make_paired(n=100, loss_mean=3_000_000, noise_std=300_000)
    out = paired_comparison(b, s)
    assert out["is_significant"]
    assert out["operationally_meaningful"]
    assert out["mean_loss_teu"] > 0
    assert out["relative_diff_pct"] > 5.0
    assert out["dz"] > 0.2


def test_paired_comparison_small_loss_not_meaningful():
    # 1% loss — statistically detectable but below 5% threshold
    b, s = _make_paired(n=100, loss_mean=100_000, noise_std=50_000)
    out = paired_comparison(b, s)
    # might be significant statistically, but NOT operationally meaningful
    assert not out["operationally_meaningful"]


def test_paired_comparison_relative_pct_correct():
    # 10% loss with clean CRN (zero noise)
    n = 50
    b = [10_000_000.0] * n
    s = [9_000_000.0] * n   # exactly 10% less
    out = paired_comparison(b, s)
    # rel_pct should be 10%, but dz will be 0 (zero std) → not meaningful
    assert abs(out["relative_diff_pct"] - 10.0) < 1e-6
    # dz = 0 because all diffs identical → operationally_meaningful = False
    assert not out["operationally_meaningful"]


def test_paired_comparison_mean_loss_zero_for_equal():
    b = [float(x) for x in range(1, 11)]
    out = paired_comparison(b, b)
    assert abs(out["mean_loss_teu"]) < 1e-9


def test_paired_comparison_p_value_in_range():
    b, s = _make_paired()
    out = paired_comparison(b, s)
    assert 0.0 <= out["p_value"] <= 1.0


def test_paired_comparison_ci_positive():
    b, s = _make_paired(loss_mean=500_000)
    out = paired_comparison(b, s)
    assert out["ci_half_width_loss_teu"] > 0


# ---------------------------------------------------------------------------
# multi_scenario_comparison
# ---------------------------------------------------------------------------

def test_multi_scenario_comparison_returns_all_ids():
    b, _ = _make_paired()
    scenarios = {i: _make_paired(loss_mean=i * 50_000)[1] for i in range(1, 6)}
    result = multi_scenario_comparison(b, scenarios)
    assert set(result.keys()) == {1, 2, 3, 4, 5}


def test_multi_scenario_comparison_each_has_required_keys():
    b, _ = _make_paired()
    scenarios = {1: _make_paired(loss_mean=500_000)[1]}
    result = multi_scenario_comparison(b, scenarios)
    assert "dz" in result[1]
    assert "operationally_meaningful" in result[1]


def test_multi_scenario_comparison_higher_loss_higher_dz():
    """Larger disruption → larger throughput loss → larger dz."""
    b, _ = _make_paired(n=100)
    s_small = _make_paired(n=100, loss_mean=200_000, noise_std=50_000)[1]
    s_large = _make_paired(n=100, loss_mean=2_000_000, noise_std=50_000)[1]
    result = multi_scenario_comparison(b, {1: s_small, 2: s_large})
    assert result[2]["dz"] > result[1]["dz"]

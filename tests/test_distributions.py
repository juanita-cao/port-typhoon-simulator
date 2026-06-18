"""Unit tests for distributions.py.

Strategy: deterministic functions → unit test; SimPy process → VRF.
All tests use fixed seeds for reproducibility.

Parameters are loaded dynamically from data/models/input_dist_record.csv.
Expected values in distributional tests are derived from the loaded params,
not from paper constants — so tests remain valid regardless of which dataset
was used to fit.
"""

import math
import sys

import numpy as np

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parents[1] / "src"))

from backend.simulation.distributions import (
    _CRANE_EFF_DIST,
    _CRANE_EFF_PARAMS,
    _CRANES_BY_GROUP,
    _GROUP_BETA,
    _GROUP_PROBS,
    _GROUP_RANGES,
    _IAT_SCALE,
    _IDLE_AFTER_DIST,
    _IDLE_AFTER_PARAMS,
    _IDLE_BEFORE_DIST,
    _IDLE_BEFORE_PARAMS,
    TEU_FACTOR,
    cranes_for_group,
    sample_crane_efficiency_lifts_per_hr,
    sample_disruption_hrs,
    sample_idle_after,
    sample_idle_before,
    sample_inter_arrival,
    sample_lpc,
    sample_lpc_group,
)

N = 20_000  # sample size for distributional checks


def _rng(seed: int = 42) -> np.random.Generator:
    return np.random.default_rng(seed)


def _theoretical_mean(dist_name: str, params: dict) -> float:
    """Theoretical mean of a fitted distribution given dist_name and params."""
    loc   = float(params.get("loc", 0.0))
    scale = float(params["scale"])
    if dist_name == "lognorm":
        return math.exp(math.log(scale) + float(params["s"]) ** 2 / 2) + loc
    if dist_name == "norm":
        return loc
    if dist_name == "expon":
        return scale + loc
    if dist_name == "gamma":
        return float(params["a"]) * scale + loc
    raise ValueError(f"Unknown dist_name: {dist_name}")


# ---------------------------------------------------------------------------
# Determinism: same seed → same output
# ---------------------------------------------------------------------------

def test_determinism_inter_arrival():
    assert sample_inter_arrival(_rng(0)) == sample_inter_arrival(_rng(0))


def test_determinism_lpc_group():
    assert sample_lpc_group(_rng(1)) == sample_lpc_group(_rng(1))


def test_determinism_crane_efficiency():
    assert sample_crane_efficiency_lifts_per_hr(_rng(2)) == sample_crane_efficiency_lifts_per_hr(_rng(2))


# ---------------------------------------------------------------------------
# sample_inter_arrival
# ---------------------------------------------------------------------------

def test_inter_arrival_positive():
    rng = _rng()
    assert all(sample_inter_arrival(rng) > 0 for _ in range(1000))


def test_inter_arrival_mean():
    rng = _rng()
    samples = [sample_inter_arrival(rng) for _ in range(N)]
    mean = sum(samples) / N
    assert abs(mean - _IAT_SCALE) / _IAT_SCALE < 0.05, (
        f"mean {mean:.3f} not within 5% of fitted scale {_IAT_SCALE:.4f}"
    )


# ---------------------------------------------------------------------------
# sample_lpc_group
# ---------------------------------------------------------------------------

def test_lpc_group_range():
    rng = _rng()
    groups = [sample_lpc_group(rng) for _ in range(N)]
    assert all(0 <= g <= 6 for g in groups)


def test_lpc_group_probabilities():
    rng = _rng()
    groups = [sample_lpc_group(rng) for _ in range(N)]
    for g, expected_p in enumerate(_GROUP_PROBS):
        observed_p = groups.count(g) / N
        tol = 3 * math.sqrt(expected_p * (1 - expected_p) / N)
        assert abs(observed_p - expected_p) < tol + 0.005, (
            f"group {g}: observed {observed_p:.4f} vs expected {expected_p:.4f}"
        )


# ---------------------------------------------------------------------------
# sample_lpc
# ---------------------------------------------------------------------------

def test_lpc_within_range():
    rng = _rng()
    for group in range(7):
        lo, hi = _GROUP_RANGES[group]
        for _ in range(200):
            lpc = sample_lpc(rng, group)
            assert lo <= lpc <= hi, f"group {group}: lpc {lpc} out of [{lo}, {hi}]"


def test_lpc_returns_int():
    rng = _rng()
    assert isinstance(sample_lpc(rng, 0), int)


# ---------------------------------------------------------------------------
# LPC distributional checks — data-derived params
# ---------------------------------------------------------------------------

def test_lpc_all_groups_sample_mean_near_theoretical():
    """For every group, sample mean must be within 5% of Beta theoretical mean."""
    rng = _rng()
    for g in range(7):
        lo, hi = _GROUP_RANGES[g]
        a, b   = _GROUP_BETA[g]
        expected = lo + (a / (a + b)) * (hi - lo)
        samples  = [sample_lpc(rng, g) for _ in range(N)]
        mean     = sum(samples) / N
        assert abs(mean - expected) / expected < 0.05, (
            f"group {g}: sample mean {mean:.0f} not within 5% of "
            f"theoretical {expected:.0f} [Beta({a},{b}) on [{lo},{hi}]]"
        )


def test_lpc_small_sample_groups_are_uniform():
    """Groups 5 and 6 have n < 30 in data → must be Beta(1,1) (small-sample fallback)."""
    for g in (5, 6):
        a, b = _GROUP_BETA[g]
        assert a == 1.0 and b == 1.0, (
            f"group {g} should be Uniform Beta(1,1) (small-sample fallback), got Beta({a},{b})"
        )


# ---------------------------------------------------------------------------
# cranes_for_group
# ---------------------------------------------------------------------------

def test_cranes_for_group_values():
    """Expected values come from the loaded fit record, not a hardcoded dataset."""
    for g, exp in enumerate(_CRANES_BY_GROUP):
        assert cranes_for_group(g) == exp


def test_cranes_for_group_positive():
    assert all(cranes_for_group(g) >= 1 for g in range(7))


# ---------------------------------------------------------------------------
# sample_crane_efficiency_lifts_per_hr
# ---------------------------------------------------------------------------

def test_crane_efficiency_positive():
    rng = _rng()
    assert all(sample_crane_efficiency_lifts_per_hr(rng) > 0 for _ in range(1000))


def test_crane_efficiency_mean():
    """Sample mean within 5% of theoretical mean from fitted params.

    Fitted as Normal from raw_data.xlsx: mean ≈ 20.23 moves/hr/crane.
    """
    expected = _theoretical_mean(_CRANE_EFF_DIST, _CRANE_EFF_PARAMS)
    rng = _rng()
    samples = [sample_crane_efficiency_lifts_per_hr(rng) for _ in range(N)]
    mean = sum(samples) / N
    assert abs(mean - expected) / expected < 0.05, (
        f"crane_eff mean {mean:.3f} not within 5% of theoretical {expected:.3f}"
    )


# ---------------------------------------------------------------------------
# sample_idle_before
# ---------------------------------------------------------------------------

def test_idle_before_non_negative():
    rng = _rng()
    assert all(sample_idle_before(rng) >= 0 for _ in range(1000))


def test_idle_before_mean():
    """Sample mean within 10% of lognormal theoretical mean (≈ 0.54 hrs)."""
    expected = _theoretical_mean(_IDLE_BEFORE_DIST, _IDLE_BEFORE_PARAMS)
    rng = _rng()
    samples = [sample_idle_before(rng) for _ in range(N)]
    mean = sum(samples) / N
    assert abs(mean - expected) / expected < 0.10, (
        f"idle_before mean {mean:.3f} not within 10% of theoretical {expected:.3f}"
    )


# ---------------------------------------------------------------------------
# sample_idle_after
# ---------------------------------------------------------------------------

def test_idle_after_non_negative():
    rng = _rng()
    assert all(sample_idle_after(rng) >= 0 for _ in range(1000))


def test_idle_after_mean():
    """Sample mean within 10% of lognormal theoretical mean (≈ 0.97 hrs)."""
    expected = _theoretical_mean(_IDLE_AFTER_DIST, _IDLE_AFTER_PARAMS)
    rng = _rng()
    samples = [sample_idle_after(rng) for _ in range(N)]
    mean = sum(samples) / N
    assert abs(mean - expected) / expected < 0.10, (
        f"idle_after mean {mean:.3f} not within 10% of theoretical {expected:.3f}"
    )


# ---------------------------------------------------------------------------
# sample_disruption_hrs
# ---------------------------------------------------------------------------

def test_disruption_zero_when_min_equals_max_zero():
    rng = _rng()
    assert sample_disruption_hrs(rng, 0, 0) == 0.0


def test_disruption_fixed_when_min_equals_max():
    rng = _rng()
    assert sample_disruption_hrs(rng, 30, 30) == 30 * 24.0


def test_disruption_within_range():
    rng = _rng()
    for _ in range(500):
        hrs = sample_disruption_hrs(rng, 10, 60)
        assert 10 * 24 <= hrs <= 60 * 24, f"disruption_hrs {hrs} out of range"


def test_disruption_units_are_hours():
    rng = _rng()
    samples = [sample_disruption_hrs(rng, 0, 30) for _ in range(N)]
    assert max(samples) <= 30 * 24 + 1e-9
    assert min(samples) >= 0


# ---------------------------------------------------------------------------
# TEU_FACTOR sanity
# ---------------------------------------------------------------------------

def test_teu_factor_value():
    assert abs(TEU_FACTOR - 1.75) < 1e-9

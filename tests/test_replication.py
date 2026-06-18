"""Contract tests for replication.py.

Strategy: test I/O structure (types, lengths, constraints).
SimPy outputs are stochastic — numerical values are not hard-coded here;
those checks happen in VRF (Phase 3).
"""

import math
import sys

import numpy as np
import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parents[1] / "src"))

from backend.schemas import DisruptionScenario, PortConfig, SimulationParams
from backend.simulation.replication import (
    _make_rngs,
    compute_n_replications,
    run_scenario,
    run_single_replication,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def port_cfg() -> PortConfig:
    from datetime import date
    return PortConfig(
        port_name="NPT_TEST",
        num_berths=16,
        num_quay_cranes=81,
        annual_throughput_base_teu=10_000_000,
        study_start_date=date(2016, 1, 1),
        study_end_date=date(2016, 12, 31),
    )


@pytest.fixture
def sim_params_fast() -> SimulationParams:
    """Very short simulation for fast test runs."""
    return SimulationParams(
        n_replications=10,
        sim_horizon_days=30,   # 30 days only
        warm_up_days=1,
        random_seed_base=99,
    )


@pytest.fixture
def scenario_cat5() -> DisruptionScenario:
    return DisruptionScenario(
        scenario_id=21,
        typhoon_cat=5,
        dist_bin=1,
        dist_min_km=0,
        dist_max_km=100,
        disruption_days_min=5,    # small for fast test
        disruption_days_max=10,
        damage_prob_min=0.8,
        damage_prob_max=1.0,
    )


# ---------------------------------------------------------------------------
# _make_rngs
# ---------------------------------------------------------------------------

def test_make_rngs_returns_three_generators():
    rngs = _make_rngs(42, 0)
    assert len(rngs) == 3
    assert all(isinstance(r, np.random.Generator) for r in rngs)


def test_make_rngs_deterministic():
    r1 = _make_rngs(42, 0)
    r2 = _make_rngs(42, 0)
    for a, b in zip(r1, r2, strict=False):
        assert a.random() == b.random()


def test_make_rngs_crn_same_rep_same_streams():
    """CRN: same (base_seed, rep) always yields identical streams.

    All scenarios call _make_rngs with the same rep index, so they share
    the same arrival/ops draws — the CRN property enabling paired t-tests.
    """
    r1 = _make_rngs(42, 7)
    r2 = _make_rngs(42, 7)
    for a, b in zip(r1, r2, strict=False):
        assert a.random() == b.random()


def test_make_rngs_different_reps_differ():
    """Different rep → different RNG streams (replications are independent)."""
    r0 = _make_rngs(42, 0)
    r1 = _make_rngs(42, 1)
    draws_0 = [g.random() for g in r0]
    draws_1 = [g.random() for g in r1]
    assert draws_0 != draws_1


def test_make_rngs_streams_independent():
    """Three streams within same call must not produce same initial draw."""
    ra, ro, rd = _make_rngs(42, 3)
    draws = {ra.random(), ro.random(), rd.random()}
    assert len(draws) == 3  # all distinct


# ---------------------------------------------------------------------------
# run_single_replication — structure
# ---------------------------------------------------------------------------

def test_single_rep_intact_returns_dict(port_cfg, sim_params_fast):
    result = run_single_replication(port_cfg, None, sim_params_fast, rep=0)
    assert isinstance(result, dict)
    assert "throughput_teu" in result
    assert "served_ship_calls" in result
    assert "disruption_hrs_sampled" in result


def test_single_rep_intact_values_positive(port_cfg, sim_params_fast):
    result = run_single_replication(port_cfg, None, sim_params_fast, rep=0)
    assert result["throughput_teu"] > 0
    assert result["served_ship_calls"] > 0


def test_single_rep_intact_no_disruption(port_cfg, sim_params_fast):
    result = run_single_replication(port_cfg, None, sim_params_fast, rep=0)
    assert result["disruption_hrs_sampled"] == 0.0


def test_single_rep_disrupted_has_nonzero_disruption(port_cfg, sim_params_fast, scenario_cat5):
    result = run_single_replication(port_cfg, scenario_cat5, sim_params_fast, rep=0)
    assert result["disruption_hrs_sampled"] > 0.0


def test_single_rep_deterministic(port_cfg, sim_params_fast):
    r1 = run_single_replication(port_cfg, None, sim_params_fast, rep=3)
    r2 = run_single_replication(port_cfg, None, sim_params_fast, rep=3)
    assert r1["throughput_teu"] == r2["throughput_teu"]
    assert r1["served_ship_calls"] == r2["served_ship_calls"]


def test_single_rep_different_reps_differ(port_cfg, sim_params_fast):
    r0 = run_single_replication(port_cfg, None, sim_params_fast, rep=0)
    r1 = run_single_replication(port_cfg, None, sim_params_fast, rep=1)
    # Same scenario but different replications should differ
    assert r0["throughput_teu"] != r1["throughput_teu"]


def test_single_rep_throughput_finite(port_cfg, sim_params_fast):
    result = run_single_replication(port_cfg, None, sim_params_fast, rep=0)
    assert math.isfinite(result["throughput_teu"])


# ---------------------------------------------------------------------------
# run_scenario — structure
# ---------------------------------------------------------------------------

def test_run_scenario_returns_dict(port_cfg, sim_params_fast):
    out = run_scenario(port_cfg, None, sim_params_fast)
    assert isinstance(out, dict)
    assert "throughputs_teu" in out
    assert "served_ship_calls" in out
    assert "disruption_hrs_sampled" in out


def test_run_scenario_length_matches_n_reps(port_cfg, sim_params_fast):
    out = run_scenario(port_cfg, None, sim_params_fast)
    n = sim_params_fast.n_replications
    assert len(out["throughputs_teu"]) == n
    assert len(out["served_ship_calls"]) == n
    assert len(out["disruption_hrs_sampled"]) == n


def test_run_scenario_all_positive(port_cfg, sim_params_fast):
    out = run_scenario(port_cfg, None, sim_params_fast)
    assert all(v > 0 for v in out["throughputs_teu"])
    assert all(v > 0 for v in out["served_ship_calls"])


def test_run_scenario_intact_disruption_zero(port_cfg, sim_params_fast):
    out = run_scenario(port_cfg, None, sim_params_fast)
    assert all(v == 0.0 for v in out["disruption_hrs_sampled"])


def test_run_scenario_disrupted_disruption_positive(port_cfg, sim_params_fast, scenario_cat5):
    out = run_scenario(port_cfg, scenario_cat5, sim_params_fast)
    assert all(v > 0 for v in out["disruption_hrs_sampled"])


def test_run_scenario_variance_nonzero(port_cfg, sim_params_fast):
    """Replications should not all be identical."""
    out = run_scenario(port_cfg, None, sim_params_fast)
    assert len(set(out["throughputs_teu"])) > 1


# ---------------------------------------------------------------------------
# compute_n_replications — Kelton (2002) formula
# ---------------------------------------------------------------------------

def test_kelton_zero_variance_returns_min():
    """Zero variance → no additional reps needed; return min_n rounded up."""
    pilot = [10_000.0] * 10
    assert compute_n_replications(pilot, min_n=10) == 10


def test_kelton_result_is_multiple_of_round_to():
    """Output must be divisible by round_to (default 10)."""
    rng = np.random.default_rng(7)
    pilot = list(rng.normal(10_000, 2_000, 10))
    n = compute_n_replications(pilot)
    assert n % 10 == 0


def test_kelton_result_at_least_min_n():
    """Output must be >= min_n even with tiny variance."""
    pilot = [10_000.0 + 1e-6 * i for i in range(10)]
    assert compute_n_replications(pilot, min_n=50) >= 50


def test_kelton_higher_variance_needs_more_reps():
    """Wider spread in pilot → larger n_final."""
    low_var  = [10_000.0 + (-1) ** i * 100  for i in range(10)]
    high_var = [10_000.0 + (-1) ** i * 3000 for i in range(10)]
    assert compute_n_replications(high_var) > compute_n_replications(low_var)


def test_kelton_tighter_margin_needs_more_reps():
    """Smaller error_margin → larger n_final."""
    pilot = [10_000.0 + (-1) ** i * 1000 for i in range(10)]
    n_loose  = compute_n_replications(pilot, error_margin=0.10)
    n_strict = compute_n_replications(pilot, error_margin=0.02)
    assert n_strict > n_loose


def test_kelton_s21_derivation_gives_270():
    """Reproduce the worked pilot-study example in design_simulation.md: s21 pilot → n_final = 270.

    s21 Cat5 0-100km: mean = 7,960,871 TEU, std = 2,876,175 TEU (n0 = 10)
    t_crit(df=9, alpha=0.05) = 2.2622  (NOT z=1.96 — z underestimates by ~33%)
    h0 = 2.2622 × 2,876,175 / √10 = 2,057,492
    h  = 0.05   × 7,960,871       =   398,044
    n  = 10 × (2,057,492 / 398,044)² = 267.2 → ceil = 268 → round_to 10 = 270
    """
    mean_s21 = 7_960_871.0
    std_s21  = 2_876_175.0
    # Build 10 samples with the exact sample mean and std (ddof=1).
    base = np.arange(10, dtype=float) - 4.5          # symmetric, mean=0
    pilot = base / base.std(ddof=1) * std_s21 + mean_s21
    assert abs(pilot.mean() - mean_s21) < 1.0
    assert abs(pilot.std(ddof=1) - std_s21) < 1.0
    assert compute_n_replications(list(pilot), error_margin=0.05) == 270

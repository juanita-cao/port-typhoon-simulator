"""Replication management for port_typhoon_simulator.

Handles CRN (Common Random Numbers) stream separation and
runs n replications per scenario.

CRN design:
  - SeedSequence([base_seed, rep]).spawn(3)
      [0] rng_arrival  — inter-arrival times
      [1] rng_ops      — LPC / crane / idle-time sampling
      [2] rng_disruption — disruption duration + start time

scenario_id is NOT part of the seed, so that rep k uses identical random
streams across all scenarios — the CRN property that makes paired t-tests valid.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.stats import t as t_dist

from backend.schemas import DisruptionScenario, PortConfig, SimulationParams
from backend.simulation.simulation import setup_and_run


def compute_n_replications(
    pilot_results: list[float],
    *,
    error_margin: float = 0.05,
    min_n: int = 10,
    round_to: int = 10,
) -> int:
    """Kelton (2002) sample-size formula.

    n ≅ n₀ × (h₀ / h)²
    where h₀ = t_crit(df=n₀-1) × std / √n₀  (95% CI half-width from pilot)
          h  = error_margin × mean             (target half-width)

    Uses t_crit (not z=1.96) because pilot n₀ is small; z underestimates n by ~33%.

    Result is rounded up to the nearest multiple of round_to (default 10)
    and is at least min_n.

    port_typhoon_simulator pilot (worked example, design_simulation.md, Target precision section):
        n₀ = 10, error_margin = 0.05, driving scenario = s21
        mean = 7,960,871 TEU, std = 2,876,175 TEU
        t_crit(df=9, alpha=0.05) = 2.262
        → n_req = 268 → n_final = 270
    """
    arr = np.asarray(pilot_results, dtype=float)
    n0 = len(arr)
    mean0 = float(arr.mean())
    std0 = float(arr.std(ddof=1))
    if mean0 <= 0 or std0 == 0:
        return int(math.ceil(min_n / round_to) * round_to)
    t_crit = float(t_dist.ppf(0.975, df=n0 - 1))
    h0 = t_crit * std0 / math.sqrt(n0)
    h = error_margin * mean0
    n_req = math.ceil(n0 * (h0 / h) ** 2)
    n_final = max(n_req, min_n)
    return int(math.ceil(n_final / round_to) * round_to)


def _make_rngs(base_seed: int, rep: int) -> tuple[
    np.random.Generator, np.random.Generator, np.random.Generator
]:
    """Return 3 independent RNG streams for one replication.

    Seed: SeedSequence([base_seed, rep]).spawn(3)
    scenario_id is excluded so that rep k uses identical streams across all
    scenarios (CRN) — enabling paired t-tests to reduce variance.
    """
    ss = np.random.SeedSequence([base_seed, rep])
    children = ss.spawn(3)
    return (
        np.random.default_rng(children[0]),  # rng_arrival
        np.random.default_rng(children[1]),  # rng_ops
        np.random.default_rng(children[2]),  # rng_disruption
    )


def run_single_replication(
    port_config: PortConfig,
    scenario: DisruptionScenario | None,
    sim_params: SimulationParams,
    rep: int,
) -> dict[str, float]:
    """Run one replication and return raw KPI dict.

    Args:
        port_config:  port parameters (berths, cranes, etc.)
        scenario:     None = intact baseline; DisruptionScenario = disrupted
        sim_params:   n_replications, sim_horizon_days, warm_up_days, etc.
        rep:          replication index (0-based), used for CRN seeding

    Returns:
        {
            "throughput_teu": float,
            "served_ship_calls": float,
            "disruption_hrs_sampled": float,
        }
    """
    rng_arrival, rng_ops, rng_disruption = _make_rngs(sim_params.random_seed_base, rep)
    return setup_and_run(
        num_berths=port_config.num_berths,
        num_quay_cranes=port_config.num_quay_cranes,
        scenario=scenario,
        rng_arrival=rng_arrival,
        rng_ops=rng_ops,
        rng_disruption=rng_disruption,
        warm_up_hrs=sim_params.warm_up_days * 24.0,
        sim_horizon_hrs=sim_params.sim_horizon_days * 24.0,
        anchorage_capacity=sim_params.anchorage_capacity,
    )


def run_scenario(
    port_config: PortConfig,
    scenario: DisruptionScenario | None,
    sim_params: SimulationParams,
) -> dict[str, list[float]]:
    """Run n_replications for one scenario and collect raw per-rep results.

    Returns:
        {
            "throughputs_teu":         list[float],  # length n_replications
            "served_ship_calls":       list[float],
            "disruption_hrs_sampled":  list[float],  # 0.0 for intact
        }
    """
    throughputs: list[float] = []
    served_calls: list[float] = []
    disruption_hrs: list[float] = []
    balked_calls: list[float] = []

    for rep in range(sim_params.n_replications):
        result = run_single_replication(port_config, scenario, sim_params, rep)
        throughputs.append(result["throughput_teu"])
        served_calls.append(result["served_ship_calls"])
        disruption_hrs.append(result["disruption_hrs_sampled"])
        balked_calls.append(result["balked_calls"])

    return {
        "throughputs_teu": throughputs,
        "served_ship_calls": served_calls,
        "disruption_hrs_sampled": disruption_hrs,
        "balked_calls": balked_calls,
    }

"""Warm-up period estimation — Welch (1983) daily moving-average method (steady-state detection).

Runs n_reps baseline replications, bins TEU throughput by day, averages across reps,
applies a window_days moving average, then identifies the first day where the smoothed
output stays within ±tol of the long-run mean for n_stable consecutive days.

Designed for low-utilisation port models where the startup transient is short (< 10 days).
For this model: n_reps=200, window=7d, tol=5% → stable at Day 5 (re-run on new data/distributions).
"""
from __future__ import annotations

import numpy as np
import simpy

from backend.simulation.distributions import (
    TEU_FACTOR,
    cranes_for_group,
    sample_crane_efficiency_lifts_per_hr,
    sample_idle_after,
    sample_idle_before,
    sample_inter_arrival,
    sample_lpc,
    sample_lpc_group,
)
from backend.simulation.simulation import Port

_HOURS_PER_DAY = 24.0


def _run_warmup_rep(
    num_berths: int,
    num_quay_cranes: int,
    n_days: int,
    seed: int,
) -> np.ndarray:
    """Single no-disruption replication — returns TEU-per-day array of length n_days."""
    ss = np.random.SeedSequence(seed)
    rng_arrival, rng_ops = (np.random.default_rng(s) for s in ss.spawn(2))

    env = simpy.Environment()
    port = Port(env, num_berths, num_quay_cranes)
    teu_per_day: np.ndarray = np.zeros(n_days)
    horizon_hrs = float(n_days * _HOURS_PER_DAY)

    def _ship(env: simpy.Environment) -> object:  # type: ignore[return]
        with port.berths.request() as req:
            yield req
            g = sample_lpc_group(rng_ops)
            lpc = sample_lpc(rng_ops, g)
            nc = cranes_for_group(g)
            eff = sample_crane_efficiency_lifts_per_hr(rng_ops)
            total_hrs = (
                sample_idle_before(rng_ops)
                + lpc / (nc * eff)
                + sample_idle_after(rng_ops)
            )
            yield env.timeout(total_hrs)
            day_idx = min(int(env.now / _HOURS_PER_DAY), n_days - 1)
            teu_per_day[day_idx] += lpc * TEU_FACTOR

    def _gen(env: simpy.Environment) -> object:  # type: ignore[return]
        while True:
            yield env.timeout(sample_inter_arrival(rng_arrival))
            env.process(_ship(env))

    env.process(_gen(env))
    env.run(until=horizon_hrs)
    return teu_per_day


def estimate_warmup_days(
    num_berths: int,
    num_quay_cranes: int,
    *,
    n_reps: int = 200,
    n_days: int = 30,
    window_days: int = 7,
    tol: float = 0.05,
    n_stable: int = 3,
) -> dict:
    """Estimate warm-up period using Welch (1983) daily moving-average method.

    Args:
        num_berths:      port berth capacity (PortConfig.num_berths)
        num_quay_cranes: total quay crane count (PortConfig.num_quay_cranes)
        n_reps:          number of replications — higher n_reps reduces noise (default 200)
        n_days:          total simulation horizon in days (default 30)
        window_days:     moving-average window width in days (default 7)
        tol:             stability tolerance as fraction of long-run mean (default 0.05 = ±5%)
        n_stable:        consecutive MA points required within tol before declaring stable

    Returns:
        dict with keys:
            stable_day   (int | None):  first day satisfying the criterion (1-indexed)
            warmup_days  (int):         stable_day, or n_days if no stable point found
            longrun_mean (float):       estimated long-run TEU/day (mean of back-half MA)
            bin_means    (list[float]): per-day mean TEU across reps (length n_days)
            ma           (list[float]): moving-average values (length n_days - window_days + 1)
            ma_days      (list[int]):   centre day (1-indexed) for each MA value
    """
    per_rep = np.array([
        _run_warmup_rep(num_berths, num_quay_cranes, n_days, seed)
        for seed in range(n_reps)
    ])

    grand = per_rep.mean(axis=0)
    ma = np.convolve(grand, np.ones(window_days) / window_days, mode="valid")
    ma_days = [i + window_days // 2 + 1 for i in range(len(ma))]

    lr = float(ma[len(ma) // 2 :].mean())

    stable_day: int | None = None
    for i, day in enumerate(ma_days):
        if abs(ma[i] - lr) / lr < tol and all(
            abs(ma[min(i + k, len(ma) - 1)] - lr) / lr < tol
            for k in range(1, n_stable)
        ):
            stable_day = day
            break

    return {
        "stable_day": stable_day,
        "warmup_days": stable_day if stable_day is not None else n_days,
        "longrun_mean": lr,
        "bin_means": grand.tolist(),
        "ma": ma.tolist(),
        "ma_days": ma_days,
    }

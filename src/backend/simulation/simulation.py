
"""SimPy DES process logic for port_typhoon_simulator.

Entities: Ship (arrives → queue for berth → service → depart)
Resources: Port.berths (SimPy Resource tokens, count = num_berths)
Disruption: event-based complete port closure (design_simulation.md, Simulation flow section)

Cranes are NOT modelled as a separate SimPy Resource — they determine service
time via cranes_for_group() instead.

No unit tests here — verified by VRF (Verification — face-validity checks).
CRN stream setup and replication management live in replication.py.

──────────────────────────────────────────────────────────────────────────────
Disruption Strategy Declaration
──────────────────────────────────────────────────────────────────────────────
strategy_name       : Event-based Complete Closure (Strategy B)
mechanism           : SimPy Event (Port._disruption_end_event)
                      Ships waiting for a berth yield on the event and unblock
                      the instant port.end_disruption() calls evt.succeed().
                      Resource._capacity is NEVER modified directly (forbidden).
in-service entities : NOT interrupted — ships already inside yield env.timeout()
                      continue their service uninterrupted.
demo simplification : Yes. Production models would call process.interrupt() on
                      in-progress service processes. This simplification is noted
                      in the comparison-table footer and design_simulation.md (Simulation flow section).
report note         : "ships already berthed at disruption onset continue service
                      uninterrupted (demo simplification; production models would
                      interrupt in-progress processes)."

anchorage mode switch (SimulationParams.anchorage_capacity):
  None (default) : legacy mode — berth queue is unbounded, so ships that arrive
                    during a disruption simply wait and are served once the port
                    reopens. Net annual throughput loss is fully "caught up"
                    unless the backlog is too large to clear within the horizon.
  int             : finite-anchorage mode — if the berth queue already holds
                    >= anchorage_capacity ships at arrival time, the new ship
                    balks (diverted/turned away): it contributes zero throughput
                    and never re-enters the queue. This models a bounded waiting
                    area and produces permanent demand loss even for short
                    disruptions, matching Arena's SEIZE-module queue-capacity
                    balking behavior. No extra RNG draw is consumed for the
                    balk decision, so CRN alignment across scenarios is
                    preserved.
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import simpy

from backend.schemas import DisruptionScenario
from backend.simulation.distributions import (
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

# ---------------------------------------------------------------------------
# Shared state objects
# ---------------------------------------------------------------------------

@dataclass
class SimStats:
    throughput_teu: float = 0.0
    served_ship_calls: int = 0
    balked_calls: int = 0


class Port:
    """SimPy resource container for the port.

    berths: 16-capacity Resource (main bottleneck).
    Disruption is signalled via a SimPy Event so waiting ships unblock the
    moment the port reopens, without needing to poll or change Resource capacity.
    """

    def __init__(
        self,
        env: simpy.Environment,
        num_berths: int,
        num_quay_cranes: int,
    ) -> None:
        self.env = env
        self.berths = simpy.Resource(env, capacity=num_berths)
        self.num_quay_cranes = num_quay_cranes
        self._disruption_end_event: simpy.Event | None = None

    @property
    def is_disrupted(self) -> bool:
        return self._disruption_end_event is not None

    def start_disruption(self) -> None:
        self._disruption_end_event = self.env.event()

    def end_disruption(self) -> None:
        evt = self._disruption_end_event
        self._disruption_end_event = None
        evt.succeed()  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# SimPy process coroutines (generator functions, not async)
# ---------------------------------------------------------------------------

def ship_process(
    env: simpy.Environment,
    port: Port,
    stats: SimStats,
    rng_ops: np.random.Generator,
    warm_up_hrs: float,
    anchorage_capacity: int | None,
):
    """Lifecycle of one vessel call: arrive → berth → (wait disruption) → service → depart."""
    # Sample all service attributes at arrival time, before any yield (CRN rule).
    # If sampling happened after yield berth_req, queue reordering caused by disruptions
    # would shift rng_ops consumption positions across scenarios, breaking CRN alignment
    # and reducing paired t-test variance reduction.
    lpc_group = sample_lpc_group(rng_ops)
    lpc = sample_lpc(rng_ops, lpc_group)
    n_cranes = cranes_for_group(lpc_group)
    efficiency_lifts_per_hr = sample_crane_efficiency_lifts_per_hr(rng_ops)
    idle_before = sample_idle_before(rng_ops)
    idle_after = sample_idle_after(rng_ops)
    service_hrs = lpc / (n_cranes * efficiency_lifts_per_hr)
    total_berth_hrs = idle_before + service_hrs + idle_after

    # Finite-anchorage mode: balk (permanently lost call) instead of joining an
    # already-full berth queue. Deterministic on queue length — no RNG consumed,
    # so this never shifts rng_ops alignment relative to legacy mode (CRN rule).
    if anchorage_capacity is not None and len(port.berths.queue) >= anchorage_capacity:
        stats.balked_calls += 1
        return

    with port.berths.request() as berth_req:
        yield berth_req  # wait until a berth is free

        # Hold the berth and block service until port reopens after disruption.
        # DEMO SIMPLIFICATION: ships that already seized a berth before the disruption
        # event continue their timeout uninterrupted. Production models would need to
        # interrupt in-progress service processes explicitly.
        if port.is_disrupted:
            yield port._disruption_end_event  # type: ignore[misc]

        yield env.timeout(total_berth_hrs)

        # Record KPIs only after warm-up period
        if env.now >= warm_up_hrs:
            stats.throughput_teu += lpc * TEU_FACTOR
            stats.served_ship_calls += 1
    # berth released automatically on context-manager exit


def _ship_generator(
    env: simpy.Environment,
    port: Port,
    stats: SimStats,
    rng_arrival: np.random.Generator,
    rng_ops: np.random.Generator,
    warm_up_hrs: float,
    anchorage_capacity: int | None,
):
    """Infinite ship arrival generator. env.run(until=T) terminates it at horizon T."""
    while True:
        yield env.timeout(sample_inter_arrival(rng_arrival))
        env.process(ship_process(env, port, stats, rng_ops, warm_up_hrs, anchorage_capacity))


def _disruption_process(
    env: simpy.Environment,
    port: Port,
    start_hr: float,
    duration_hrs: float,
):
    """Inject a complete-closure disruption at start_hr lasting duration_hrs."""
    yield env.timeout(start_hr)
    port.start_disruption()
    yield env.timeout(duration_hrs)
    port.end_disruption()


# ---------------------------------------------------------------------------
# Top-level entry point (called by replication.py)
# ---------------------------------------------------------------------------

def setup_and_run(
    *,
    num_berths: int,
    num_quay_cranes: int,
    scenario: DisruptionScenario | None,
    rng_arrival: np.random.Generator,
    rng_ops: np.random.Generator,
    rng_disruption: np.random.Generator,
    warm_up_hrs: float,
    sim_horizon_hrs: float,
    anchorage_capacity: int | None = None,
) -> dict[str, float]:
    """Create a SimPy environment, run one replication, return KPI dict.

    Args:
        anchorage_capacity: None = legacy unlimited-queue mode (default).
            int = finite-anchorage balking mode (see disruption strategy
            declaration docstring above).

    Returns:
        {
            "throughput_teu": float,      # annualized TEU/year (measurement window scaled to 365 days)
            "served_ship_calls": float,   # completed vessel calls after warm-up
            "disruption_hrs_sampled": float,  # 0.0 for intact / baseline
            "balked_calls": float,        # vessel calls turned away (0.0 in legacy mode)
        }
    """
    env = simpy.Environment()
    port = Port(env, num_berths, num_quay_cranes)
    stats = SimStats()

    env.process(_ship_generator(
        env, port, stats, rng_arrival, rng_ops, warm_up_hrs, anchorage_capacity
    ))

    disruption_hrs_sampled = 0.0
    if scenario is not None and scenario.disruption_days_max > 0:
        disruption_hrs_sampled = sample_disruption_hrs(
            rng_disruption,
            scenario.disruption_days_min,
            scenario.disruption_days_max,
        )
        # Disruption must start after warm-up and leave room to complete within horizon.
        # If disruption is so long it can't fit, start it right at warm-up.
        latest_start_hr = sim_horizon_hrs - disruption_hrs_sampled
        if latest_start_hr > warm_up_hrs:
            start_hr = float(rng_disruption.uniform(warm_up_hrs, latest_start_hr))
        else:
            start_hr = warm_up_hrs

        env.process(_disruption_process(env, port, start_hr, disruption_hrs_sampled))

    env.run(until=sim_horizon_hrs)

    measurement_hrs = sim_horizon_hrs - warm_up_hrs
    annualization_factor = (365.0 * 24.0) / measurement_hrs if measurement_hrs > 0 else 1.0
    return {
        "throughput_teu": stats.throughput_teu * annualization_factor,
        "served_ship_calls": float(stats.served_ship_calls),
        "disruption_hrs_sampled": disruption_hrs_sampled,
        "balked_calls": float(stats.balked_calls),
    }

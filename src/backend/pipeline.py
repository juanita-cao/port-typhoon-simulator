"""Pipeline orchestrator — chains E2→E5 into a single run.

Computes one shared output_dir up front and passes it to every node, so all
artifacts land in one outputs/{timestamp}_{run_id}/ folder instead of
each node creating its own. E1 and E6 are not implemented yet (see
design_backend.md), so this covers the DES → loss-aggregation slice only.
"""

from __future__ import annotations

import json
from pathlib import Path

from backend.artifacts import _default_output_dir, build_run_metadata
from backend.e_nodes import (
    _load_port_components,
    _load_port_config,
    _load_scenario_matrix,
    _mc_loss_for_scenario,
    e2_run_simulation,
    e3_estimate_physical_loss,
    e4_estimate_economic_loss,
    e5_aggregate_losses,
)
from backend.schemas import SimulationParams
from backend.simulation.output_analysis import compute_scenario_stats
from backend.simulation.replication import run_scenario

_CONFIGS_DIR = Path(__file__).parent / "configs"


def run_full_pipeline(
    sim_params: SimulationParams | None = None,
    port_name: str = "NPT",
    handling_charge_usd_per_teu: float = 120.0,
    n_mc_samples: int = 10_000,
    random_seed_base: int = 42,
    verbose: bool = False,
) -> dict:
    """Run E2 → E3 → E4 → E5, persisting all artifacts into one shared folder.

    Returns:
        {"status": "OK", "output_dir": Path, "loss_profile": LossProfile} on success.
        E2's own {"status": "FAILED_VALIDATION", ...} dict if VRF/VLD fails —
        E3-E5 are skipped in that case (no point estimating loss on rejected output).
    """
    output_dir = _default_output_dir(build_run_metadata())
    output_dir.mkdir(parents=True, exist_ok=True)

    sim_results = e2_run_simulation(
        sim_params=sim_params, port_name=port_name, verbose=verbose, output_dir=output_dir,
    )
    if isinstance(sim_results, dict):
        return sim_results

    physical = e3_estimate_physical_loss(
        port_name=port_name,
        n_mc_samples=n_mc_samples,
        random_seed_base=random_seed_base,
        verbose=verbose,
        output_dir=output_dir,
    )
    economic = e4_estimate_economic_loss(
        sim_results,
        handling_charge_usd_per_teu=handling_charge_usd_per_teu,
        verbose=verbose,
        output_dir=output_dir,
    )
    scenario_matrix = _load_scenario_matrix()
    port_config = _load_port_config(port_name)
    loss_profile = e5_aggregate_losses(
        physical, economic, scenario_matrix, port_config,
        verbose=verbose, output_dir=output_dir,
    )

    return {"status": "OK", "output_dir": output_dir, "loss_profile": loss_profile}


def run_single_scenario_pipeline(
    scenario_id: int,
    sim_params: SimulationParams | None = None,
    port_name: str = "NPT",
    handling_charge_usd_per_teu: float = 120.0,
    n_mc_samples: int = 10_000,
    random_seed_base: int = 42,
    verbose: bool = False,
) -> dict:
    """Run E2 (intact + 1 scenario) → E3 (1 scenario) → E4 → historical from lookup.

    Faster than run_full_pipeline: runs SimPy for 2 scenarios only (intact + selected)
    instead of 26. Historical total/annual-avg come from scenario_loss_lookup.json
    (pre-computed from a prior full run) so E5 is not re-executed.

    Args:
        scenario_id: 1–25, maps to a row in scenario_params.json

    Returns on success:
        {
            "status": "OK",
            "output_dir": Path,
            "result": {
                "scenario_id": int,
                "throughput_mean_teu": float,
                "intact_throughput_mean_teu": float,
                "decreased_teu": float,
                "decreased_teu_pct": float,
                "physical_loss_mean_usd": float,
                "physical_loss_p95_usd": float,
                "equipment_losses": [
                    {"label": str, "mean_usd": float, "p95_usd": float}, ...
                ],
                "economic_loss_usd": float,
                "total_loss_usd": float,
                "historical_total_usd": float,
                "historical_annual_avg_usd": float,
                "typhoon_history": [
                    {"year": int, "name": str, "category": int,
                     "dist_km": float, "loss_usd": float}, ...
                ],
            }
        }

    Returns on failure:
        {"status": "FAILED_*", "reason": ..., "output_dir": Path}
    """
    if not (1 <= scenario_id <= 25):
        raise ValueError(f"scenario_id must be 1–25, got {scenario_id}")

    if sim_params is None:
        sim_params = SimulationParams()

    output_dir = _default_output_dir(build_run_metadata())
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- Load config ---
    port_config = _load_port_config(port_name)
    scenario_matrix = _load_scenario_matrix()
    port_components = _load_port_components(port_name)
    scenario = next((s for s in scenario_matrix.scenarios if s.scenario_id == scenario_id), None)
    if scenario is None:
        return {
            "status": "FAILED_EXCEPTION",
            "reason": f"scenario_id {scenario_id} not found in scenario matrix",
            "output_dir": output_dir,
        }

    # --- E2: SimPy — intact baseline + selected scenario only ---
    if verbose:
        print(f"[E2-single] Running intact + scenario {scenario_id} "
              f"({sim_params.n_replications} reps)…")
    try:
        intact_out = run_scenario(port_config, None, sim_params)
        disrupted_out = run_scenario(port_config, scenario, sim_params)
    except Exception as exc:
        return {
            "status": "FAILED_EXCEPTION",
            "reason": str(exc),
            "output_dir": output_dir,
        }

    intact_stats = compute_scenario_stats(
        intact_out["throughputs_teu"],
        intact_out["served_ship_calls"],
        intact_out["disruption_hrs_sampled"],
    )
    disrupted_stats = compute_scenario_stats(
        disrupted_out["throughputs_teu"],
        disrupted_out["served_ship_calls"],
        disrupted_out["disruption_hrs_sampled"],
    )

    intact_teu = intact_stats["mean_teu"]
    disrupted_teu = disrupted_stats["mean_teu"]

    if disrupted_teu > intact_teu:
        return {
            "status": "FAILED_EXCEPTION",
            "reason": (
                f"Disrupted throughput ({disrupted_teu:.0f}) exceeds intact "
                f"({intact_teu:.0f}) — model sanity check failed"
            ),
            "output_dir": output_dir,
        }

    # --- E3: MC physical loss — selected scenario with equipment breakdown ---
    phys = _mc_loss_for_scenario(
        scenario, port_components, n_mc_samples,
        seed=random_seed_base + scenario_id,
    )
    if verbose:
        print(f"[E3-single] loss_mean={phys.loss_mean_usd/1e6:.2f}M  "
              f"p95={phys.loss_p95_usd/1e6:.2f}M")

    # --- E4: deterministic economic loss ---
    decreased_teu = intact_teu - disrupted_teu
    decreased_teu_pct = (decreased_teu / intact_teu) * 100
    economic_loss_usd = decreased_teu * handling_charge_usd_per_teu
    total_loss_usd = phys.loss_mean_usd + economic_loss_usd

    # --- Historical data from pre-computed lookup + presets ---
    lookup_path = _CONFIGS_DIR / "scenario_loss_lookup.json"
    presets_path = _CONFIGS_DIR / "typhoon_presets.json"
    loss_lookup: dict[str, dict] = json.loads(lookup_path.read_text())
    presets: list[dict] = json.loads(presets_path.read_text())

    port_config_raw = json.loads((_CONFIGS_DIR / "port_configs.json").read_text())
    study = port_config_raw["ports"][port_name]
    start_year = int(study["study_start_date"][:4])
    end_year = int(study["study_end_date"][:4])
    historical_study_years = end_year - start_year

    historical_total_usd = sum(
        scenario_matrix.historical_frequencies.get(int(sid), 0.0)
        * entry["total_usd"]
        * historical_study_years
        for sid, entry in loss_lookup.items()
    )
    historical_annual_avg_usd = historical_total_usd / historical_study_years if historical_study_years else 0.0

    typhoon_history = sorted(
        [
            {
                "year": p["year"],
                "name": p["name"],
                "category": p["category"],
                "dist_km": p["strike_dist_km"],
                "loss_usd": p["loss_usd"],
            }
            for p in presets
        ],
        key=lambda r: r["year"],
        reverse=True,
    )

    result = {
        "scenario_id": scenario_id,
        "throughput_mean_teu": disrupted_teu,
        "intact_throughput_mean_teu": intact_teu,
        "decreased_teu": decreased_teu,
        "decreased_teu_pct": decreased_teu_pct,
        "physical_loss_mean_usd": phys.loss_mean_usd,
        "physical_loss_p95_usd": phys.loss_p95_usd,
        "equipment_losses": [
            {"label": "Quay Crane", "mean_usd": phys.quay_crane_loss_mean_usd,
             "p95_usd": phys.quay_crane_loss_p95_usd},
            {"label": "Gantry Crane", "mean_usd": phys.gantry_crane_loss_mean_usd,
             "p95_usd": phys.gantry_crane_loss_p95_usd},
            {"label": "Container Truck", "mean_usd": phys.container_truck_loss_mean_usd,
             "p95_usd": phys.container_truck_loss_p95_usd},
            {"label": "Other Equipment", "mean_usd": phys.other_loss_mean_usd,
             "p95_usd": phys.other_loss_p95_usd},
        ],
        "economic_loss_usd": economic_loss_usd,
        "total_loss_usd": total_loss_usd,
        "historical_total_usd": historical_total_usd,
        "historical_annual_avg_usd": historical_annual_avg_usd,
        "typhoon_history": typhoon_history,
    }

    if verbose:
        print(f"[pipeline-single] scenario={scenario_id} "
              f"decreased_teu={decreased_teu:.0f} ({decreased_teu_pct:.1f}%) "
              f"EL=${economic_loss_usd/1e6:.1f}M  TL=${total_loss_usd/1e6:.1f}M")

    return {"status": "OK", "output_dir": output_dir, "result": result}

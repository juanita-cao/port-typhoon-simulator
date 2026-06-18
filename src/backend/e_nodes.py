"""E-node implementations for port_typhoon_simulator.

E1: e1_load_typhoon_data
  - Parses IBTrACS WP-basin track data; classifies each qualifying storm
    into one of the 25 disruption scenarios (category x distance bin)
  - Returns TyphoonTrackData (validated Pydantic schema)

E2: e2_run_simulation
  - Loads PortConfig and ScenarioMatrix from pipeline context
  - Runs intact baseline + all 25 disruption scenarios
  - Returns SimulationResults (validated Pydantic schema)

E3: e3_estimate_physical_loss
  - Monte Carlo over each scenario's damage-probability range × total
    equipment replacement cost (no SimPy; pure NumPy sampling)
  - Returns PhysicalLossEstimates (validated Pydantic schema)
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd

from backend.artifacts import (
    build_run_metadata,
    save_e2_artifacts,
    save_e3_artifacts,
    save_e4_artifacts,
    save_e5_artifacts,
)
from backend.schemas import (
    ComponentSpec,
    DisruptionScenario,
    EconomicLossEstimates,
    EconomicLossPerScenario,
    LossProfile,
    PhysicalLossEstimates,
    PhysicalLossPerScenario,
    PortComponents,
    PortConfig,
    PortMarker,
    ScenarioLoss,
    ScenarioMatrix,
    SimulationParams,
    SimulationResults,
    TrackPoint,
    TyphoonEvent,
    TyphoonTrackData,
    TyphoonTrackViz,
    VizPayload,
)
from backend.simulation.replication import run_scenario
from backend.simulation.report import (
    build_comparison_table,
    build_simulation_results,
    format_comparison_matrix,
)
from backend.simulation.warmup_analysis import estimate_warmup_days

_CONFIGS_DIR = Path(__file__).parent / "configs"

# =============================================================================
# E1 · e1_load_typhoon_data
# =============================================================================

# Wind-speed fill default (used only where IBTrACS USA_WIND is missing),
# by Saffir-Simpson category — mid-range of the SS scale, in knots.
_CAT_VMAX_KT: dict[int, float] = {-1: 25, 0: 45, 1: 70, 2: 90, 3: 105, 4: 125, 5: 150}


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _dist_bin_for(dist_km: float, radius_km: float) -> int:
    bin_width = radius_km / 5
    for i in range(1, 6):
        if dist_km <= bin_width * i:
            return i
    return 5


def _fill_vmax(wind: pd.Series, cat: pd.Series) -> pd.Series:
    """Interpolate missing USA_WIND values; fall back to a category default."""
    s = pd.to_numeric(wind, errors="coerce").interpolate(method="linear", limit_direction="both")
    mask = s.isna()
    if mask.any():
        s[mask] = cat[mask].map(lambda c: _CAT_VMAX_KT.get(c, _CAT_VMAX_KT[1]))
    return s.round(1)


def e1_load_typhoon_data(
    ibtracs_path: Path,
    port_lat: float,
    port_lon: float,
    radius_km: float = 500.0,
    study_years: tuple[int, int] = (1994, 2026),
    port_name: str = "NPT",
    track_box_km: float = 2000.0,
) -> TyphoonTrackData:
    """Parse IBTrACS WP-basin data into a validated TyphoonTrackData (E1).

    A storm qualifies if at least one of its track points falls within
    radius_km of the port. Each qualifying storm is classified into one of
    the 25 disruption scenarios by its peak Saffir-Simpson category while
    near the port and its closest-approach distance bin. Every track point
    within track_box_km is kept (for map animation); points beyond it are
    dropped to keep the payload small.
    """
    df = pd.read_csv(
        ibtracs_path,
        skiprows=[1],  # row 1 = units line
        na_values=[" ", ""],
        low_memory=False,
        usecols=["SID", "SEASON", "NAME", "ISO_TIME", "LAT", "LON", "USA_WIND", "USA_SSHS"],
        dtype={"SEASON": "Int64", "USA_SSHS": "Int64"},
    )
    df = df[df["SEASON"].between(study_years[0], study_years[1])].copy()
    df["ISO_TIME"] = pd.to_datetime(df["ISO_TIME"], errors="coerce")
    df["LAT"] = pd.to_numeric(df["LAT"], errors="coerce")
    df["LON"] = pd.to_numeric(df["LON"], errors="coerce")
    df.dropna(subset=["LAT", "LON", "ISO_TIME"], inplace=True)

    df["dist_km"] = df.apply(
        lambda r: _haversine_km(r["LAT"], r["LON"], port_lat, port_lon), axis=1
    )

    events: list[TyphoonEvent] = []
    for sid, grp in df.groupby("SID"):
        grp_sorted = grp.sort_values("ISO_TIME")
        near = grp_sorted[grp_sorted["dist_km"] <= radius_km]
        if near.empty:
            continue

        cat_series = near["USA_SSHS"].dropna()
        if cat_series.empty:
            cat_series = grp_sorted["USA_SSHS"].dropna()
        if cat_series.empty:
            continue
        max_cat = int(cat_series.max())
        if max_cat < 1:
            continue  # tropical storm or weaker — skip

        closest = near.loc[near["dist_km"].idxmin()]
        min_dist = float(closest["dist_km"])
        dbin = _dist_bin_for(min_dist, radius_km)
        scen_id = (max_cat - 1) * 5 + dbin

        box = grp_sorted[grp_sorted["dist_km"] <= track_box_km]
        if len(box) < 2:
            continue  # TrackPoint schema requires >= 2 points

        cat_col = pd.to_numeric(box["USA_SSHS"], errors="coerce").fillna(1).clip(-1, 5)
        vmax = _fill_vmax(box["USA_WIND"], cat_col)

        track_points = [
            TrackPoint(
                lat=round(float(r["LAT"]), 4),
                lon=round(float(r["LON"]), 4),
                wind_speed_kt=float(vmax.loc[idx]),
                timestamp=r["ISO_TIME"],
            )
            for idx, r in box.iterrows()
        ]

        cat_at_closest = (
            pd.to_numeric(pd.Series([closest["USA_SSHS"]]), errors="coerce").fillna(1).clip(-1, 5)
        )
        wind_at_strike = float(_fill_vmax(pd.Series([closest["USA_WIND"]]), cat_at_closest).iloc[0])

        events.append(TyphoonEvent(
            storm_id=str(sid),
            name=str(grp_sorted["NAME"].iloc[0]).strip().title(),
            year=int(grp_sorted["SEASON"].iloc[0]),
            month=int(closest["ISO_TIME"].month),
            track_points=track_points,
            min_distance_km=round(min_dist, 1),
            wind_speed_at_strike_kt=wind_at_strike,
            saffir_simpson_cat=max_cat,
            distance_bin=dbin,
            scenario_id=scen_id,
        ))

    events.sort(key=lambda e: e.year)
    return TyphoonTrackData(
        port_name=port_name,
        port_lat=port_lat,
        port_lon=port_lon,
        study_years=study_years,
        events=events,
        total_event_count=len(events),
    )


# =============================================================================
# Shared config loaders
# =============================================================================

def _load_port_config(port_name: str = "NPT") -> PortConfig:
    data = json.loads((_CONFIGS_DIR / "port_configs.json").read_text())
    p = data["ports"][port_name]
    return PortConfig(
        port_name=p["port_name"],
        num_berths=p["num_berths"],
        num_quay_cranes=p["num_quay_cranes"],
        annual_throughput_base_teu=p["annual_throughput_base_teu"],
        study_start_date=p["study_start_date"],
        study_end_date=p["study_end_date"],
    )


def _load_scenarios() -> list[DisruptionScenario]:
    data = json.loads((_CONFIGS_DIR / "scenario_params.json").read_text())
    return [DisruptionScenario(**s) for s in data["scenarios"]]


def _load_scenario_matrix() -> ScenarioMatrix:
    data = json.loads((_CONFIGS_DIR / "scenario_params.json").read_text())
    return ScenarioMatrix(
        scenarios=[DisruptionScenario(**s) for s in data["scenarios"]],
        historical_frequencies={int(k): v for k, v in data["historical_frequencies"].items()},
    )


def _load_port_components(port_name: str = "NPT") -> PortComponents:
    data = json.loads((_CONFIGS_DIR / "port_configs.json").read_text())
    c = data["ports"][port_name]["components"]
    return PortComponents(
        quay_cranes=ComponentSpec(**c["quay_cranes"]),
        gantry_cranes=ComponentSpec(**c["gantry_cranes"]),
        container_trucks=ComponentSpec(**c["container_trucks"]),
        other_equipment_value_usd=c["other_equipment_value_usd"],
    )


# =============================================================================
# E2 · e2_run_simulation
# =============================================================================

def e2_run_simulation(
    sim_params: SimulationParams | None = None,
    port_name: str = "NPT",
    verbose: bool = False,
    save_artifacts: bool = True,
    auto_warmup: bool = True,
    output_dir: Path | str | None = None,
) -> SimulationResults | dict:
    """Run the full simulation pipeline: intact baseline + 25 scenarios.

    Args:
        sim_params:     override defaults (n_replications, horizon, warm_up, etc.)
        port_name:      port key in port_configs.json (default "NPT")
        verbose:        print the 5×5 comparison matrix + statistical-comparison signal summary after completion
        save_artifacts: persist artifacts to outputs/{timestamp}_{run_id}/ (default True)
        auto_warmup:    if True, run Welch analysis and override warm_up_days;
                        if False, use sim_params.warm_up_days as-is (no Welch run)
        output_dir:     override the auto-generated outputs/{timestamp}_{run_id}/ folder
                         (pass the same dir to e3/e4/e5 to persist a full pipeline run
                         into one shared folder for the frontend to read)

    Returns:
        SimulationResults on success.
        dict {"status": "FAILED_VALIDATION", "failed_stage": ..., ...} if VRF or VLD fails.
    """
    if sim_params is None:
        sim_params = SimulationParams()

    port_config = _load_port_config(port_name)
    scenarios = _load_scenarios()

    # --- Welch warm-up analysis (steady-state detection, mandatory) ---
    if auto_warmup:
        if verbose:
            print("[E2] Running Welch warm-up analysis...")
        warmup_result = estimate_warmup_days(
            num_berths=port_config.num_berths,
            num_quay_cranes=port_config.num_quay_cranes,
        )
        sim_params = sim_params.model_copy(
            update={"warm_up_days": warmup_result["warmup_days"]}
        )
    else:
        warmup_result = {
            "warmup_days": sim_params.warm_up_days,
            "stable_day": None,
            "method": "manual (auto_warmup=False)",
        }
    warmup_result["warm_up_days_used"] = sim_params.warm_up_days
    warmup_result["auto_warmup"] = auto_warmup

    welch_tag = (f"[Welch stable_day={warmup_result['stable_day']}]"
                 if auto_warmup else "[manual]")

    t0 = time.perf_counter()

    if verbose:
        print(f"[E2] Starting: {sim_params.n_replications} reps × 26 scenarios "
              f"({port_config.port_name}, horizon={sim_params.sim_horizon_days}d, "
              f"warm_up={sim_params.warm_up_days}d {welch_tag})")

    # --- intact baseline (scenario_id = 0) ---
    intact_outputs = run_scenario(port_config, None, sim_params)
    if verbose:
        mean_teu = sum(intact_outputs["throughputs_teu"]) / len(intact_outputs["throughputs_teu"])
        print(f"  [intact] mean_teu={mean_teu/1e6:.3f}M")

    # --- 25 disrupted scenarios ---
    disrupted_outputs: dict[int, dict[str, list[float]]] = {}
    for sc in scenarios:
        disrupted_outputs[sc.scenario_id] = run_scenario(port_config, sc, sim_params)
        if verbose:
            mean_teu = sum(disrupted_outputs[sc.scenario_id]["throughputs_teu"]) / sim_params.n_replications
            print(f"  [s{sc.scenario_id:02d} cat{sc.typhoon_cat} bin{sc.dist_bin}] mean_teu={mean_teu/1e6:.3f}M")

    elapsed = time.perf_counter() - t0

    results = build_simulation_results(
        intact_outputs=intact_outputs,
        disrupted_outputs=disrupted_outputs,
        n_replications=sim_params.n_replications,
    )

    # --- artifact persistence + V&V failure path (F1–F5) ---
    if save_artifacts:
        meta = build_run_metadata(
            n_replications=sim_params.n_replications,
            random_seed_base=sim_params.random_seed_base,
        )
        # F1: persist all artifacts first (including VRF/VLD reports) so failure evidence is on disk
        saved_dir, vrf_report, vld_result = save_e2_artifacts(
            results, run_metadata=meta, output_dir=output_dir, warmup_result=warmup_result
        )

        if not vrf_report["summary"]["vrf_passed"]:
            print("[E2] ❌ VRF FAILED — aborting")          # F5
            return {                                               # F2 / F3 / F4
                "status": "FAILED_VALIDATION",
                "failed_stage": "VRF",
                "reason": vrf_report["summary"],
                "artifacts_dir": str(saved_dir),
            }

        if not vld_result["all_passed"]:
            print("[E2] ❌ VLD FAILED — aborting")          # F5
            return {                                               # F2 / F3 / F4
                "status": "FAILED_VALIDATION",
                "failed_stage": "VLD",
                "reason": {k: v for k, v in vld_result.items()
                           if k not in ("run_id", "timestamp")},
                "artifacts_dir": str(saved_dir),
            }

    # --- verbose statistical-comparison output (only reached when V&V passed) ---
    if verbose:
        intact_ci = results.intact.throughput_ci_half_width
        print(
            f"[E2] Done in {elapsed:.1f}s\n"
            f"     Intact throughput: {results.intact.throughput_mean_teu / 1e6:.3f}M TEU"
            f"  (95% CI ±{intact_ci / 1e6:.3f}M, n={sim_params.n_replications} reps)\n"
            f"     VRF PASSED · VLD PASSED"
        )
        comp = build_comparison_table(results, include_paired_stats=True)
        print(format_comparison_matrix(comp))
        n_meaningful = int(comp["operationally_meaningful"].sum())
        print(
            f"\n  Signal: {n_meaningful}/25 scenarios operationally meaningful"
            f"  (≥5% loss AND |dz|≥0.2)\n"
        )
        if save_artifacts:
            print(f"  Artifacts saved → {saved_dir}")

    return results


# =============================================================================
# E3 · e3_estimate_physical_loss
# =============================================================================

def _mc_loss_for_scenario(
    scenario: DisruptionScenario,
    components: PortComponents,
    n_mc_samples: int,
    seed: int,
) -> PhysicalLossPerScenario:
    rng = np.random.default_rng(seed)
    damage_probs = rng.uniform(scenario.damage_prob_min, scenario.damage_prob_max, size=n_mc_samples)

    qc_exp = components.quay_cranes.count * components.quay_cranes.unit_value_usd
    rtg_exp = components.gantry_cranes.count * components.gantry_cranes.unit_value_usd
    truck_exp = components.container_trucks.count * components.container_trucks.unit_value_usd
    other_exp = components.other_equipment_value_usd

    qc_losses = damage_probs * qc_exp
    rtg_losses = damage_probs * rtg_exp
    truck_losses = damage_probs * truck_exp
    other_losses = damage_probs * other_exp
    total_losses = qc_losses + rtg_losses + truck_losses + other_losses

    loss_std = float(np.std(total_losses, ddof=1)) if n_mc_samples > 1 else 0.0
    return PhysicalLossPerScenario(
        scenario_id=scenario.scenario_id,
        loss_mean_usd=float(np.mean(total_losses)),
        loss_std_usd=loss_std,
        loss_p95_usd=float(np.percentile(total_losses, 95)),
        quay_crane_loss_mean_usd=float(np.mean(qc_losses)),
        quay_crane_loss_p95_usd=float(np.percentile(qc_losses, 95)),
        gantry_crane_loss_mean_usd=float(np.mean(rtg_losses)),
        gantry_crane_loss_p95_usd=float(np.percentile(rtg_losses, 95)),
        container_truck_loss_mean_usd=float(np.mean(truck_losses)),
        container_truck_loss_p95_usd=float(np.percentile(truck_losses, 95)),
        other_loss_mean_usd=float(np.mean(other_losses)),
        other_loss_p95_usd=float(np.percentile(other_losses, 95)),
    )


def e3_estimate_physical_loss(
    scenario_matrix: ScenarioMatrix | None = None,
    port_components: PortComponents | None = None,
    n_mc_samples: int = 10_000,
    port_name: str = "NPT",
    random_seed_base: int = 42,
    verbose: bool = False,
    save_artifacts: bool = True,
    output_dir: Path | str | None = None,
) -> PhysicalLossEstimates:
    """Monte Carlo physical loss estimate per scenario (E3, see design_backend.md, Pipeline table).

    For each of the 25 scenarios, sample damage_prob ~ Uniform(damage_prob_min,
    damage_prob_max) n_mc_samples times and scale by the port's total equipment
    replacement cost. Seed is scenario_id + random_seed_base, so repeated calls with
    the same seed reproduce identical output (deterministic reproducibility).

    Args:
        save_artifacts: persist artifacts to outputs/{timestamp}_{run_id}/ (default True)
        output_dir:     pass the same dir used by e2 to persist into one shared
                         pipeline-run folder instead of creating a new one
    """
    if scenario_matrix is None:
        scenario_matrix = _load_scenario_matrix()
    if port_components is None:
        port_components = _load_port_components(port_name)

    estimates = [
        _mc_loss_for_scenario(
            sc, port_components, n_mc_samples, seed=random_seed_base + sc.scenario_id
        )
        for sc in scenario_matrix.scenarios
    ]

    if verbose:
        total_exposure_usd = (
            port_components.quay_cranes.count * port_components.quay_cranes.unit_value_usd
            + port_components.gantry_cranes.count * port_components.gantry_cranes.unit_value_usd
            + port_components.container_trucks.count * port_components.container_trucks.unit_value_usd
            + port_components.other_equipment_value_usd
        )
        print(f"[E3] total_exposure_usd={total_exposure_usd/1e6:.1f}M, n_mc_samples={n_mc_samples}")
        for est in estimates:
            print(f"  s{est.scenario_id:02d}: loss_mean={est.loss_mean_usd/1e6:.2f}M  "
                  f"p95={est.loss_p95_usd/1e6:.2f}M")

    result = PhysicalLossEstimates(estimates=estimates, n_mc_samples=n_mc_samples)

    if save_artifacts:
        meta = build_run_metadata(random_seed_base=random_seed_base, n_mc_samples=n_mc_samples)
        saved_dir = save_e3_artifacts(result, run_metadata=meta, output_dir=output_dir)
        if verbose:
            print(f"  Artifacts saved → {saved_dir}")

    return result


# =============================================================================
# E4 · e4_estimate_economic_loss
# =============================================================================

def e4_estimate_economic_loss(
    sim_results: SimulationResults,
    handling_charge_usd_per_teu: float,
    save_artifacts: bool = True,
    output_dir: Path | str | None = None,
    verbose: bool = False,
) -> EconomicLossEstimates:
    """Deterministic economic loss per scenario (E4, see design_backend.md, Pipeline table).

    EL = (intact_teu - disrupted_teu) × handling_charge_usd_per_teu.

    Args:
        save_artifacts: persist artifacts to outputs/{timestamp}_{run_id}/ (default True)
        output_dir:     pass the same dir used by e2/e3 to persist into one shared
                         pipeline-run folder instead of creating a new one
    """
    intact_teu = sim_results.intact.throughput_mean_teu

    estimates = []
    for run in sim_results.disrupted:
        if run.throughput_mean_teu > intact_teu:
            raise ValueError(
                f"scenario {run.scenario_id}: disrupted throughput exceeds intact "
                f"({run.throughput_mean_teu} > {intact_teu})"
            )
        decreased_teu = intact_teu - run.throughput_mean_teu
        decreased_teu_pct = (decreased_teu / intact_teu) * 100
        economic_loss_usd = decreased_teu * handling_charge_usd_per_teu
        estimates.append(EconomicLossPerScenario(
            scenario_id=run.scenario_id,
            decreased_teu=decreased_teu,
            decreased_teu_pct=decreased_teu_pct,
            economic_loss_usd=economic_loss_usd,
        ))

    result = EconomicLossEstimates(
        estimates=estimates,
        handling_charge_usd_per_teu=handling_charge_usd_per_teu,
    )

    if save_artifacts:
        meta = build_run_metadata(handling_charge_usd_per_teu=handling_charge_usd_per_teu)
        saved_dir = save_e4_artifacts(result, run_metadata=meta, output_dir=output_dir)
        if verbose:
            print(f"  Artifacts saved → {saved_dir}")

    return result


# =============================================================================
# E5 · e5_aggregate_losses
# =============================================================================

_PREDICTED_YEARS = 5  # matches LossProfile.predicted_5yr_usd


def e5_aggregate_losses(
    physical: PhysicalLossEstimates,
    economic: EconomicLossEstimates,
    scenario_matrix: ScenarioMatrix,
    port_config: PortConfig,
    save_artifacts: bool = True,
    output_dir: Path | str | None = None,
    verbose: bool = False,
) -> LossProfile:
    """Aggregate physical + economic loss per scenario into a LossProfile (E5).

    TL = PL + EL per scenario; historical_total = Σ(annual_frequency × TL ×
    historical_study_years), where historical_study_years is derived from
    port_config.study_start_date/study_end_date (the IBTrACS historical record
    span, e.g. 1994-2015 = 21 years — distinct from the SimPy simulation horizon,
    which is set separately via SimulationParams.sim_horizon_days).
    predicted_5yr_usd projects the same per-scenario annual frequency forward
    over a fixed 5-year window.

    Args:
        save_artifacts: persist artifacts to outputs/{timestamp}_{run_id}/ (default True)
        output_dir:     pass the same dir used by e2/e3/e4 to persist into one shared
                         pipeline-run folder instead of creating a new one
    """
    historical_study_years = (
        port_config.study_end_date.year - port_config.study_start_date.year
    )

    phys_by_id = {e.scenario_id: e for e in physical.estimates}
    econ_by_id = {e.scenario_id: e for e in economic.estimates}
    sc_by_id = {s.scenario_id: s for s in scenario_matrix.scenarios}

    scenario_losses = []
    for sid in range(1, 26):
        if sid not in phys_by_id:
            raise KeyError(f"scenario {sid} missing from physical loss estimates")
        if sid not in econ_by_id:
            raise KeyError(f"scenario {sid} missing from economic loss estimates")
        if sid not in sc_by_id:
            raise KeyError(f"scenario {sid} missing from scenario_matrix")
        if sid not in scenario_matrix.historical_frequencies:
            raise KeyError(f"scenario {sid} missing from historical_frequencies")

        pl = phys_by_id[sid].loss_mean_usd
        el = econ_by_id[sid].economic_loss_usd
        sc = sc_by_id[sid]
        scenario_losses.append(ScenarioLoss(
            scenario_id=sid,
            typhoon_cat=sc.typhoon_cat,
            dist_bin=sc.dist_bin,
            physical_loss_mean_usd=pl,
            economic_loss_usd=el,
            total_loss_usd=pl + el,
            annual_frequency=scenario_matrix.historical_frequencies[sid],
        ))

    historical_total_usd = sum(
        sl.annual_frequency * sl.total_loss_usd * historical_study_years for sl in scenario_losses
    )
    historical_annual_avg_usd = historical_total_usd / historical_study_years
    predicted_5yr_usd = sum(
        sl.annual_frequency * sl.total_loss_usd * _PREDICTED_YEARS for sl in scenario_losses
    )
    predicted_annual_avg_usd = predicted_5yr_usd / _PREDICTED_YEARS

    worst = max(scenario_losses, key=lambda sl: sl.total_loss_usd)

    if predicted_annual_avg_usd > 10 * historical_annual_avg_usd:
        print(
            f"[E5] WARN: predicted annual avg (${predicted_annual_avg_usd:,.0f}) "
            f"> 10x historical annual avg (${historical_annual_avg_usd:,.0f}) — model sanity check"
        )

    result = LossProfile(
        scenario_losses=scenario_losses,
        historical_total_usd=historical_total_usd,
        historical_annual_avg_usd=historical_annual_avg_usd,
        predicted_5yr_usd=predicted_5yr_usd,
        predicted_annual_avg_usd=predicted_annual_avg_usd,
        worst_case_scenario_id=worst.scenario_id,
        worst_case_total_loss_usd=worst.total_loss_usd,
    )

    if save_artifacts:
        meta = build_run_metadata()
        saved_dir = save_e5_artifacts(result, run_metadata=meta, output_dir=output_dir)
        if verbose:
            print(f"  Artifacts saved → {saved_dir}")

    return result


# =============================================================================
# E6 · e6_build_viz_payload
# =============================================================================

# Saffir-Simpson category color scheme — matches the frontend's _CAT_COLOR.
_CAT_COLOR_RGBA: dict[int, list[int]] = {
    1: [79, 179, 255, 200],
    2: [0, 196, 140, 200],
    3: [255, 184, 0, 200],
    4: [255, 122, 0, 200],
    5: [255, 59, 48, 200],
}


def e6_build_viz_payload(track_data: TyphoonTrackData) -> VizPayload:
    """Flatten TyphoonTrackData into map-ready track + port marker data (E6).

    Scope: track display only. The risk heatmap and 5x5 scenario grid that
    were originally planned for this step were descoped from the frontend
    (see design_frontend.md) — VizPayload only carries what the UI renders.
    """
    tracks = [
        TyphoonTrackViz(
            storm_id=event.storm_id,
            name=event.name,
            path=[[pt.lon, pt.lat] for pt in event.track_points],
            color_rgba=_CAT_COLOR_RGBA[event.saffir_simpson_cat],
            category=event.saffir_simpson_cat,
        )
        for event in track_data.events
    ]
    port_marker = PortMarker(
        lon=track_data.port_lon,
        lat=track_data.port_lat,
        name=track_data.port_name,
    )
    return VizPayload(typhoon_tracks=tracks, port_marker=port_marker)

"""Simulation API router — two endpoints:

GET  /api/results   →  serve pre-computed outputs/latest/
POST /api/simulate  →  run e2_run_simulation() in thread, return same shape
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.e_nodes import e2_run_simulation
from backend.schemas import SimulationParams

router = APIRouter(prefix="/api")

_SERVICE_ROOT = Path(__file__).parents[3]   # routers→backend→src→service_root
_OUTPUTS_DIR = _SERVICE_ROOT / "outputs" / "latest"

# ── response models ──────────────────────────────────────────────────────────

class ScenarioRow(BaseModel):
    scenario_id: int
    typhoon_cat: int
    dist_bin: int
    dist_range_km: str
    decreased_teu: float
    decreased_pct: float
    disruption_days_mean: float
    dz: float
    p_value: float
    is_significant: bool
    is_significant_holm: bool
    decision_signal: str
    operationally_meaningful: bool


class PortAnimConfig(BaseModel):
    num_berths: int
    mean_interarrival_hrs: float   # drives ship spawn rate in animation


class SimResultsResponse(BaseModel):
    run_metadata: dict
    intact_throughput_mean_teu: float
    n_replications: int
    port_anim: PortAnimConfig
    scenarios: list[ScenarioRow]


class SimulateRequest(BaseModel):
    n_replications: int = 20      # quick-mode default

# ── helpers ──────────────────────────────────────────────────────────────────

def _load_precomputed() -> SimResultsResponse:
    meta_path = _OUTPUTS_DIR / "e2_run_metadata.json"
    output_path = _OUTPUTS_DIR / "e2_output.json"
    stats_path = _OUTPUTS_DIR / "e2_comparison_stats.csv"

    if not meta_path.exists() or not output_path.exists() or not stats_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Pre-computed results not found. Run POST /api/simulate first.",
        )

    meta = json.loads(meta_path.read_text())
    output = json.loads(output_path.read_text())
    stats_df = pd.read_csv(stats_path)

    return _build_response(meta, output, stats_df)


def _build_response(meta: dict, output: dict, stats_df: pd.DataFrame) -> SimResultsResponse:
    intact_mean = output["intact"]["throughput_mean_teu"]
    n_reps = output["n_replications_used"]

    scenarios = []
    for _, row in stats_df.iterrows():
        sid = int(row["scenario_id"])
        disrupted_rows = [r for r in output["disrupted"] if r["scenario_id"] == sid]
        disruption_days = disrupted_rows[0]["disruption_days_mean"] if disrupted_rows else 0.0

        scenarios.append(ScenarioRow(
            scenario_id=sid,
            typhoon_cat=int(row["typhoon_cat"]),
            dist_bin=int(row["dist_bin"]),
            dist_range_km=str(row["dist_range_km"]),
            decreased_teu=float(row["decreased_teu"]),
            decreased_pct=float(row["decreased_pct"]),
            disruption_days_mean=float(disruption_days or 0.0),
            dz=float(row["dz"]),
            p_value=float(row["p_value"]),
            is_significant=bool(row["is_significant"]),
            is_significant_holm=bool(row["is_significant_holm"]),
            decision_signal=str(row["decision_signal"]),
            operationally_meaningful=bool(row["operationally_meaningful"]),
        ))

    return SimResultsResponse(
        run_metadata=meta,
        intact_throughput_mean_teu=intact_mean,
        n_replications=n_reps,
        port_anim=PortAnimConfig(
            num_berths=16,
            mean_interarrival_hrs=47.04,   # 1.96 days × 24
        ),
        scenarios=scenarios,
    )


def _run_and_build(n_reps: int) -> SimResultsResponse:
    from backend.artifacts import build_run_metadata, save_e2_artifacts
    from backend.simulation.report import build_comparison_table

    params = SimulationParams(n_replications=n_reps)
    results = e2_run_simulation(sim_params=params, save_artifacts=True)

    meta = build_run_metadata(
        n_replications=n_reps,
        random_seed_base=params.random_seed_base,
    )
    save_e2_artifacts(results, run_metadata=meta)

    comp_df = build_comparison_table(results, include_paired_stats=True)
    output_dict = json.loads(results.model_dump_json())
    return _build_response(meta, output_dict, comp_df)

# ── endpoints ────────────────────────────────────────────────────────────────

@router.get("/results", response_model=SimResultsResponse)
async def get_results():
    """Return pre-computed results from outputs/latest/."""
    return _load_precomputed()


@router.post("/simulate", response_model=SimResultsResponse)
async def run_simulate(body: SimulateRequest):
    """Run e2_run_simulation in a thread; returns when complete (~30s for 20 reps)."""
    try:
        result = await asyncio.to_thread(_run_and_build, body.n_replications)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return result

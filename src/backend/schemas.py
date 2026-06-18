"""Pydantic data contracts for port_typhoon_simulator pipeline.

Covers all E-node boundaries defined in design_backend.md (Data contracts section).
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

# ---------------------------------------------------------------------------
# E1 Output — TyphoonTrackData
# ---------------------------------------------------------------------------

class TrackPoint(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    wind_speed_kt: float = Field(ge=0)
    timestamp: datetime


class TyphoonEvent(BaseModel):
    storm_id: str = Field(min_length=1)
    name: str
    year: int = Field(ge=1900, le=2100)
    month: int = Field(ge=1, le=12)
    track_points: list[TrackPoint] = Field(min_length=2)
    min_distance_km: float = Field(ge=0)
    wind_speed_at_strike_kt: float = Field(ge=0)
    saffir_simpson_cat: int = Field(ge=1, le=5)
    distance_bin: int = Field(ge=1, le=5)
    scenario_id: int = Field(ge=1, le=25)


class TyphoonTrackData(BaseModel):
    port_name: str = Field(min_length=1)
    port_lat: float = Field(ge=-90, le=90)
    port_lon: float = Field(ge=-180, le=180)
    study_years: tuple[int, int]
    events: list[TyphoonEvent]
    total_event_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _years_ordered(self) -> TyphoonTrackData:
        if self.study_years[0] >= self.study_years[1]:
            raise ValueError("study_years[0] must be < study_years[1]")
        return self


# ---------------------------------------------------------------------------
# E1 Internal — ScenarioMatrix
# ---------------------------------------------------------------------------

class DisruptionScenario(BaseModel):
    scenario_id: int = Field(ge=1, le=25)
    typhoon_cat: int = Field(ge=1, le=5)
    dist_bin: int = Field(ge=1, le=5)
    dist_min_km: int
    dist_max_km: int
    disruption_days_min: int = Field(ge=0)
    disruption_days_max: int

    damage_prob_min: float = Field(ge=0, le=1)
    damage_prob_max: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _bounds_valid(self) -> DisruptionScenario:
        if self.disruption_days_max < self.disruption_days_min:
            raise ValueError("disruption_days_max must be >= disruption_days_min")
        if self.damage_prob_max < self.damage_prob_min:
            raise ValueError("damage_prob_max must be >= damage_prob_min")
        return self


class ScenarioMatrix(BaseModel):
    scenarios: list[DisruptionScenario] = Field(min_length=25, max_length=25)
    historical_frequencies: dict[int, float]

    @model_validator(mode="after")
    def _freq_keys_valid(self) -> ScenarioMatrix:
        for k, v in self.historical_frequencies.items():
            if not (1 <= k <= 25):
                raise ValueError(f"frequency key {k} out of range 1-25")
            if v < 0:
                raise ValueError(f"frequency for scenario {k} must be >= 0")
        return self


# ---------------------------------------------------------------------------
# E2 Input — PortConfig
# ---------------------------------------------------------------------------

class PortConfig(BaseModel):
    port_name: str = Field(min_length=1)
    num_berths: int = Field(ge=1, le=100)
    num_quay_cranes: int = Field(ge=1, le=500)
    annual_throughput_base_teu: float = Field(gt=0)
    study_start_date: date
    study_end_date: date

    @model_validator(mode="after")
    def _dates_ordered(self) -> PortConfig:
        if self.study_end_date <= self.study_start_date:
            raise ValueError("study_end_date must be > study_start_date")
        return self


# ---------------------------------------------------------------------------
# E2 Input — SimulationParams
# ---------------------------------------------------------------------------

class SimulationParams(BaseModel):
    n_replications: int = Field(default=270, ge=10)
    sim_horizon_days: int = Field(default=365, gt=0)
    warm_up_days: int = Field(default=5, ge=0)
    random_seed_base: int = Field(default=42)
    target_ci_half_width: float = Field(default=0.05, gt=0, lt=1)
    # None = legacy mode (unlimited anchorage queue, ships always caught up after disruption).
    # int  = finite anchorage capacity; ships arriving when the berth queue is already at
    #        capacity balk (permanently lost demand, no catch-up). See the disruption
    #        strategy declaration in simulation.py.
    anchorage_capacity: int | None = Field(default=None, ge=1)


# ---------------------------------------------------------------------------
# E2 Output — SimulationResults
# ---------------------------------------------------------------------------

class SimRunResult(BaseModel):
    scenario_id: int = Field(ge=0, le=25)       # 0 = intact
    throughput_mean_teu: float = Field(gt=0)
    throughput_ci_half_width: float = Field(ge=0)
    raw_throughputs: list[float]                 # per-rep values for paired comparison tests
    served_ship_calls_mean: float = Field(gt=0)
    disruption_days_mean: float | None = Field(default=None, ge=0)
    # Normality check & CI method selection (recorded for audit)
    normality_p_value: float | None = Field(default=None, ge=0, le=1)
    is_normal: bool | None = Field(default=None)
    ci_method: str = Field(default="t-CI")

    @model_validator(mode="after")
    def _raw_non_empty(self) -> SimRunResult:
        if len(self.raw_throughputs) == 0:
            raise ValueError("raw_throughputs must not be empty")
        return self


class SimulationResults(BaseModel):
    intact: SimRunResult
    disrupted: list[SimRunResult] = Field(min_length=25, max_length=25)
    n_replications_used: int = Field(ge=10)

    @model_validator(mode="after")
    def _intact_scenario_id(self) -> SimulationResults:
        if self.intact.scenario_id != 0:
            raise ValueError("intact.scenario_id must be 0")
        return self


# ---------------------------------------------------------------------------
# E3 Input — PortComponents
# ---------------------------------------------------------------------------

class ComponentSpec(BaseModel):
    count: int = Field(gt=0)
    unit_value_usd: float = Field(gt=0)


class PortComponents(BaseModel):
    quay_cranes: ComponentSpec
    gantry_cranes: ComponentSpec
    container_trucks: ComponentSpec
    other_equipment_value_usd: float = Field(ge=0)


# ---------------------------------------------------------------------------
# E3 Output — PhysicalLossEstimates
# ---------------------------------------------------------------------------

class PhysicalLossPerScenario(BaseModel):
    scenario_id: int = Field(ge=1, le=25)
    loss_mean_usd: float = Field(ge=0)
    loss_std_usd: float = Field(ge=0)
    loss_p95_usd: float = Field(ge=0)
    # Per-equipment breakdown (Table 7 components); default 0 keeps existing callers valid
    quay_crane_loss_mean_usd: float = Field(ge=0, default=0.0)
    quay_crane_loss_p95_usd: float = Field(ge=0, default=0.0)
    gantry_crane_loss_mean_usd: float = Field(ge=0, default=0.0)
    gantry_crane_loss_p95_usd: float = Field(ge=0, default=0.0)
    container_truck_loss_mean_usd: float = Field(ge=0, default=0.0)
    container_truck_loss_p95_usd: float = Field(ge=0, default=0.0)
    other_loss_mean_usd: float = Field(ge=0, default=0.0)
    other_loss_p95_usd: float = Field(ge=0, default=0.0)

    @model_validator(mode="after")
    def _p95_ge_mean(self) -> PhysicalLossPerScenario:
        if self.loss_p95_usd < self.loss_mean_usd:
            raise ValueError("loss_p95_usd must be >= loss_mean_usd")
        return self


class PhysicalLossEstimates(BaseModel):
    estimates: list[PhysicalLossPerScenario] = Field(min_length=25, max_length=25)
    n_mc_samples: int = Field(gt=0)


# ---------------------------------------------------------------------------
# E4 Output — EconomicLossEstimates
# ---------------------------------------------------------------------------

class EconomicLossPerScenario(BaseModel):
    scenario_id: int = Field(ge=1, le=25)
    decreased_teu: float = Field(ge=0)
    decreased_teu_pct: float = Field(ge=0, le=100)
    economic_loss_usd: float = Field(ge=0)


class EconomicLossEstimates(BaseModel):
    estimates: list[EconomicLossPerScenario] = Field(min_length=25, max_length=25)
    handling_charge_usd_per_teu: float = Field(gt=0)


# ---------------------------------------------------------------------------
# E5 Output — LossProfile
# ---------------------------------------------------------------------------

class ScenarioLoss(BaseModel):
    scenario_id: int = Field(ge=1, le=25)
    typhoon_cat: int = Field(ge=1, le=5)
    dist_bin: int = Field(ge=1, le=5)
    physical_loss_mean_usd: float = Field(ge=0)
    economic_loss_usd: float = Field(ge=0)
    total_loss_usd: float = Field(ge=0)
    annual_frequency: float = Field(ge=0)


class LossProfile(BaseModel):
    scenario_losses: list[ScenarioLoss] = Field(min_length=25, max_length=25)
    historical_total_usd: float = Field(ge=0)
    historical_annual_avg_usd: float = Field(ge=0)
    predicted_5yr_usd: float = Field(ge=0)
    predicted_annual_avg_usd: float = Field(ge=0)
    worst_case_scenario_id: int = Field(ge=1, le=25)
    worst_case_total_loss_usd: float = Field(gt=0)


# ---------------------------------------------------------------------------
# E6 Output — VizPayload
# ---------------------------------------------------------------------------

class TyphoonTrackViz(BaseModel):
    storm_id: str
    name: str
    path: list[list[float]]          # [[lon, lat], ...]
    color_rgba: list[int]            # [R, G, B, A]
    category: int = Field(ge=1, le=5)


class RiskPoint(BaseModel):
    lon: float
    lat: float
    weight: float = Field(ge=0)


class ScenarioCell(BaseModel):
    scenario_id: int = Field(ge=1, le=25)
    typhoon_cat: int = Field(ge=1, le=5)
    dist_bin: int = Field(ge=1, le=5)
    total_loss_usd: float = Field(ge=0)
    color_rgba: list[int]
    label: str


class PortMarker(BaseModel):
    lon: float
    lat: float
    name: str


class VizPayload(BaseModel):
    typhoon_tracks: list[TyphoonTrackViz]
    risk_heatmap_points: list[RiskPoint]
    scenario_grid_cells: list[ScenarioCell] = Field(min_length=25, max_length=25)
    port_marker: PortMarker


# ---------------------------------------------------------------------------
# Pipeline Context
# ---------------------------------------------------------------------------

class PipelineContext(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=datetime.now)
    port_config: PortConfig | None = None
    typhoon_track_data: TyphoonTrackData | None = None
    scenario_matrix: ScenarioMatrix | None = None
    simulation_results: SimulationResults | None = None
    physical_loss_estimates: PhysicalLossEstimates | None = None
    economic_loss_estimates: EconomicLossEstimates | None = None
    loss_profile: LossProfile | None = None
    viz_payload: VizPayload | None = None
    v1_report: dict | None = None
    completed_nodes: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    node_timings_ms: dict[str, float] = Field(default_factory=dict)

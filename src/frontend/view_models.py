"""ViewModel Contract for Port Typhoon Simulator (Artifact 6).

Rules:
- Only build_*_viewmodel() accesses backend result nested fields.
- Render functions accept only ViewModel objects, never PipelineContext.
- _MOCK_* fixtures enable Step 8 Mock Shell without real pipeline.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# ViewModels
# ---------------------------------------------------------------------------

class TyphoonInfoViewModel(BaseModel):
    """Sidebar typhoon info card — CONFIG state."""

    typhoon_id: str
    display_name: str
    category: int = Field(ge=1, le=5)
    strike_dist_km: float = Field(ge=0)
    disruption_label: str


class EquipmentLossRow(BaseModel):
    label: str
    mean_usd: float = Field(ge=0)
    p95_usd: float = Field(ge=0)


class HistoricalTyphoonRow(BaseModel):
    year: int
    name: str
    category: int = Field(ge=1, le=5)
    dist_km: float = Field(ge=0)
    loss_usd: float = Field(ge=0)


class ResultsViewModel(BaseModel):
    """All data required by _render_results_tab1 and _render_results_tab2."""

    typhoon_display_name: str

    # Tab 1 — Loss Summary
    decreased_teu: float = Field(ge=0)
    decreased_teu_pct: float = Field(ge=0, le=100)
    equipment_rows: list[EquipmentLossRow]          # exactly 4; total row computed in render
    physical_loss_total_mean_usd: float = Field(ge=0)
    physical_loss_total_p95_usd: float = Field(ge=0)
    economic_loss_usd: float = Field(ge=0)
    total_loss_usd: float = Field(ge=0)

    # Tab 2 — Historical Records (1994–2025)
    historical_total_usd: float = Field(ge=0)
    historical_annual_avg_usd: float = Field(ge=0)
    historical_typhoons: list[HistoricalTyphoonRow]  # sorted year desc

    # Export
    output_dir: str


# ---------------------------------------------------------------------------
# Transform functions (only here may backend result fields be accessed)
# ---------------------------------------------------------------------------

def build_typhoon_info_viewmodel(preset: dict) -> TyphoonInfoViewModel:
    """Transform a typhoon_presets.json entry into sidebar display data."""
    return TyphoonInfoViewModel(
        typhoon_id=preset["sid"],
        display_name=preset["display_name"],
        category=preset["category"],
        strike_dist_km=preset["strike_dist_km"],
        disruption_label=preset["disruption_label"],
    )


def build_results_viewmodel(result: dict, typhoon_info: TyphoonInfoViewModel, output_dir: str = "") -> ResultsViewModel:
    """Transform run_single_scenario_pipeline result dict → ResultsViewModel.

    Only this function accesses result's nested fields (F-VM-Results node).
    `result` is the value of pipeline_return["result"].
    """
    equipment_rows = [
        EquipmentLossRow(
            label=eq["label"],
            mean_usd=eq["mean_usd"],
            p95_usd=eq["p95_usd"],
        )
        for eq in result["equipment_losses"]
    ]
    historical_typhoons = sorted(
        [
            HistoricalTyphoonRow(
                year=t["year"],
                name=t["name"],
                category=t["category"],
                dist_km=t["dist_km"],
                loss_usd=t["loss_usd"],
            )
            for t in result["typhoon_history"]
        ],
        key=lambda r: r.year,
        reverse=True,
    )
    return ResultsViewModel(
        typhoon_display_name=typhoon_info.display_name,
        decreased_teu=result["decreased_teu"],
        decreased_teu_pct=result["decreased_teu_pct"],
        equipment_rows=equipment_rows,
        physical_loss_total_mean_usd=result["physical_loss_mean_usd"],
        physical_loss_total_p95_usd=result["physical_loss_p95_usd"],
        economic_loss_usd=result["economic_loss_usd"],
        total_loss_usd=result["total_loss_usd"],
        historical_total_usd=result["historical_total_usd"],
        historical_annual_avg_usd=result["historical_annual_avg_usd"],
        historical_typhoons=historical_typhoons,
        output_dir=output_dir,
    )


# ---------------------------------------------------------------------------
# Mock fixtures (Option B — PTS_MOCK=1; see feature_flags.py)
# ---------------------------------------------------------------------------

_MOCK_TYPHOON_INFO_VM = TyphoonInfoViewModel(
    typhoon_id="2012201N15129",
    display_name="Vicente 2012",
    category=4,
    strike_dist_km=130.1,
    disruption_label="50–190 days",
)

_MOCK_RESULTS_VM = ResultsViewModel(
    typhoon_display_name="Vicente 2012",
    decreased_teu=1_850.0,
    decreased_teu_pct=28.4,
    equipment_rows=[
        EquipmentLossRow(label="Quay Cranes",    mean_usd=21_400_000, p95_usd=38_200_000),
        EquipmentLossRow(label="RTG Cranes",     mean_usd=8_600_000,  p95_usd=16_100_000),
        EquipmentLossRow(label="Buildings",      mean_usd=3_200_000,  p95_usd=6_400_000),
        EquipmentLossRow(label="Yard Equipment", mean_usd=2_100_000,  p95_usd=4_300_000),
    ],
    physical_loss_total_mean_usd=100_900_000,
    physical_loss_total_p95_usd=180_000_000,
    economic_loss_usd=9_100_000,
    total_loss_usd=110_000_000,
    historical_total_usd=6_023_000_000,
    historical_annual_avg_usd=188_200_000,
    historical_typhoons=[
        HistoricalTyphoonRow(year=2023, name="Saola",    category=4, dist_km=62,  loss_usd=309_600_000),
        HistoricalTyphoonRow(year=2018, name="Mangkhut", category=2, dist_km=137, loss_usd=49_400_000),
        HistoricalTyphoonRow(year=2017, name="Hato",     category=3, dist_km=93,  loss_usd=167_700_000),
        HistoricalTyphoonRow(year=2014, name="Rammasun", category=5, dist_km=425, loss_usd=25_300_000),
        HistoricalTyphoonRow(year=2012, name="Vicente",  category=4, dist_km=130, loss_usd=110_000_000),
    ],
    output_dir="outputs/mock_run",
)

"""Assembles raw replication outputs into validated Pydantic schemas.

build_simulation_results():
  - Takes intact + 25-scenario run_scenario() outputs
  - Applies output_analysis to compute stats per scenario
  - Returns SimulationResults (validated at E2 boundary)

build_comparison_table():
  - Post-processes SimulationResults into a flat comparison DataFrame
  - One row per disrupted scenario (25 rows)
  - Table 9-compatible: decreased_teu, decreased_pct, plus optional statistical-comparison stats
  - Used by E2 verbose output and downstream E4/V2 audit builders

format_table9():
  - Renders the comparison DataFrame as a 5×5 console matrix matching paper Table 9
"""

from __future__ import annotations

import pandas as pd

from backend.schemas import SimRunResult, SimulationResults
from backend.simulation.output_analysis import compute_scenario_stats, multi_scenario_comparison

_DIST_RANGES = {1: "0–100", 2: "101–200", 3: "201–300", 4: "301–400", 5: "401–500"}


def _build_run_result(
    scenario_id: int,
    throughputs: list[float],
    served_calls: list[float],
    disruption_hrs: list[float],
) -> SimRunResult:
    stats = compute_scenario_stats(throughputs, served_calls, disruption_hrs)
    return SimRunResult(
        scenario_id=scenario_id,
        throughput_mean_teu=stats["mean_teu"],
        throughput_ci_half_width=stats["ci_half_width_teu"],
        raw_throughputs=throughputs,
        served_ship_calls_mean=stats["served_calls_mean"],
        disruption_days_mean=stats["disruption_days_mean"] if scenario_id > 0 else None,
        normality_p_value=stats["normality_p_value"],
        is_normal=stats["is_normal"],
        ci_method=stats["ci_method"],
    )


def build_simulation_results(
    intact_outputs: dict[str, list[float]],
    disrupted_outputs: dict[int, dict[str, list[float]]],
    n_replications: int,
) -> SimulationResults:
    """Assemble SimulationResults from raw run_scenario() outputs.

    Args:
        intact_outputs:    output of run_scenario(..., scenario=None)
        disrupted_outputs: {scenario_id: run_scenario(..., scenario=s)} for all 25 scenarios
        n_replications:    total reps actually used

    Returns:
        SimulationResults (Pydantic-validated)
    """
    intact = _build_run_result(
        scenario_id=0,
        throughputs=intact_outputs["throughputs_teu"],
        served_calls=intact_outputs["served_ship_calls"],
        disruption_hrs=intact_outputs["disruption_hrs_sampled"],
    )

    disrupted: list[SimRunResult] = []
    for sid in sorted(disrupted_outputs.keys()):
        out = disrupted_outputs[sid]
        disrupted.append(_build_run_result(
            scenario_id=sid,
            throughputs=out["throughputs_teu"],
            served_calls=out["served_ship_calls"],
            disruption_hrs=out["disruption_hrs_sampled"],
        ))

    return SimulationResults(
        intact=intact,
        disrupted=disrupted,
        n_replications_used=n_replications,
    )


def build_comparison_table(
    results: SimulationResults,
    *,
    include_paired_stats: bool = True,
) -> pd.DataFrame:
    """Build scenario comparison table in Table 9 format (plus optional statistical-comparison stats).

    Args:
        results:              validated SimulationResults from E2
        include_paired_stats: if True, appends Cohen's dz / p-value / decision columns
                              (requires raw_throughputs in each SimRunResult)

    Returns:
        DataFrame with 25 rows, one per disrupted scenario. Columns:
            scenario_id, typhoon_cat, dist_bin, dist_range_km
            intact_teu, disrupted_teu, decreased_teu, decreased_pct
            ci_hw_teu, disruption_days_mean, served_ship_calls
            [dz, p_value, is_significant, operationally_meaningful]  <- if include_paired_stats

    Continuity note (E3/E4):
        decreased_teu and decreased_pct are what e4_estimate_economic_loss() needs.
        E4 can call build_comparison_table() directly or re-derive from SimulationResults.
    """
    intact_teu = results.intact.throughput_mean_teu
    baseline_raw = results.intact.raw_throughputs

    # Pre-compute Holm-corrected stats for all 25 scenarios at once.
    # Calling multi_scenario_comparison here (not per-row paired_comparison) ensures
    # is_significant reflects FWER-controlled decisions across the full comparison set.
    holm_results: dict = {}
    if include_paired_stats:
        scenarios_raw = {r.scenario_id: r.raw_throughputs for r in results.disrupted}
        holm_results = multi_scenario_comparison(baseline_raw, scenarios_raw)

    rows = []
    for r in results.disrupted:
        decreased = intact_teu - r.throughput_mean_teu
        cat = (r.scenario_id - 1) // 5 + 1
        dist_bin = (r.scenario_id - 1) % 5 + 1
        row: dict = {
            "scenario_id": r.scenario_id,
            "typhoon_cat": cat,
            "dist_bin": dist_bin,
            "dist_range_km": _DIST_RANGES[dist_bin],
            "intact_teu": intact_teu,
            "disrupted_teu": r.throughput_mean_teu,
            "decreased_teu": decreased,
            "decreased_pct": decreased / intact_teu * 100.0,
            "ci_hw_teu": r.throughput_ci_half_width,
            "disruption_days_mean": r.disruption_days_mean,
            "served_ship_calls": r.served_ship_calls_mean,
            # Normality check & CI method selection
            "normality_p_value": r.normality_p_value,
            "is_normal":         r.is_normal,
            "ci_method":         r.ci_method,
        }
        if include_paired_stats:
            comp = holm_results[r.scenario_id]
            row.update({
                "t_statistic":            comp["t_statistic"],
                "mean_loss_teu":          comp["mean_loss_teu"],
                "ci_half_width_loss_teu": comp["ci_half_width_loss_teu"],
                "dz":                     comp["dz"],
                "p_value":                comp["p_value"],
                "is_significant_raw":     comp["is_significant_raw"],
                "is_significant":         comp["is_significant"],
                "is_significant_holm":    comp["is_significant_holm"],
                "correction_method":      comp["correction_method"],
                "operationally_meaningful": comp["operationally_meaningful"],
                "decision_signal":        comp["decision_signal"],
            })
        rows.append(row)

    return pd.DataFrame(rows)


def format_table9(df: pd.DataFrame) -> str:
    """Render comparison DataFrame as Table 9-style 5×5 console matrix.

    Columns: distance bins (km) — 0–100, 101–200, 201–300, 301–400, 401–500
    Rows (per typhoon category): Decreased TEU | Decreased/Intact %
    """
    col_w = 12
    label_w = 26
    bins = [1, 2, 3, 4, 5]
    header_bins = "".join(f"{_DIST_RANGES[b]:>{col_w}}" for b in bins)
    sep = "─" * (14 + label_w + col_w * len(bins))

    lines = [
        sep,
        f"{'Typhoon Scale':<14}{'Output':<{label_w}}" + header_bins,
        sep,
    ]

    for cat in range(1, 6):
        cat_df = df[df["typhoon_cat"] == cat].sort_values("dist_bin")
        row_abs = f"  Category {cat}   {'Decreased (TEU)':<{label_w}}"
        row_pct = f"{'':14}{'Decreased/Intact (%)':<{label_w}}"
        for _, r in cat_df.iterrows():
            row_abs += f"{r['decreased_teu']:>{col_w},.0f}"
            row_pct += f"{r['decreased_pct']:>{col_w - 1}.2f}%"
        lines.append(row_abs)
        lines.append(row_pct)
        if cat < 5:
            lines.append("")

    lines.append(sep)
    lines.append(
        "Note: ships already berthed at disruption onset continue service uninterrupted "
        "(demo simplification; production models would interrupt in-progress processes)."
    )
    return "\n".join(lines)

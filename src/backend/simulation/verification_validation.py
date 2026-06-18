"""V&V module for port_typhoon_simulator.

VRF (Verification — programmatic face-validity checks) on SimulationResults.
VLD (Validation — sanity-check comparison against an independent benchmark
           reference) — compare simulated output against real-world
           operational records, annualised for a like-for-like check.

Benchmark reference (illustrative — calibrated for this public demo, since the
original confidential operational dataset cannot be redistributed; the demo
data pipeline and V&V mechanics are otherwise unchanged):
    ship_arrivals_actual   = 2270  (7-month count)
    throughput_teu_actual  = 5_705_000  (7-month TEU)
    observation_months     = 7

We annualize to compare with our 365-day simulation output.
Annualisation multiplier = 12 / 7.
VLD tolerance: ±20% (sanity check; no paired observations available).
"""

from __future__ import annotations

from backend.schemas import SimulationResults

# ---------------------------------------------------------------------------
# Benchmark reference constants (illustrative, see module docstring)
# ---------------------------------------------------------------------------

_BENCHMARK_SHIP_ARRIVALS_7MO: int = 2270
_BENCHMARK_THROUGHPUT_TEU_7MO: float = 5_705_000.0
_BENCHMARK_OBSERVATION_MONTHS: int = 7
_ANNUALISE: float = 12.0 / _BENCHMARK_OBSERVATION_MONTHS

BENCHMARK_REF = {
    "source":               "Illustrative benchmark reference (demo)",
    "port":                 "NPT (demo terminal)",
    "observation_period":   "2016-01-01 to 2016-07-31",
    "observation_months":   _BENCHMARK_OBSERVATION_MONTHS,
    "ship_arrivals_7mo":    _BENCHMARK_SHIP_ARRIVALS_7MO,
    "throughput_teu_7mo":   _BENCHMARK_THROUGHPUT_TEU_7MO,
    "ship_arrivals_annual": round(_BENCHMARK_SHIP_ARRIVALS_7MO * _ANNUALISE, 1),
    "throughput_teu_annual": round(_BENCHMARK_THROUGHPUT_TEU_7MO * _ANNUALISE, 0),
}


# ---------------------------------------------------------------------------
# VRF: face-validity checks
# ---------------------------------------------------------------------------

def run_vrf_checks(results: SimulationResults) -> list[dict]:
    """Run programmatic VRF (Verification — face-validity) checks.

    Returns a list of check-result dicts, one per check:
        check_id       int
        description    str
        expected       str   (human-readable criterion)
        actual         str   (formatted observed value)
        passed         bool
    """
    checks: list[dict] = []
    intact_teu = results.intact.throughput_mean_teu
    intact_calls = results.intact.served_ship_calls_mean
    intact_ci_hw = results.intact.throughput_ci_half_width
    disrupted = sorted(results.disrupted, key=lambda r: r.scenario_id)

    def _row(cid: int, desc: str, expected: str, actual: str, passed: bool) -> dict:
        return {
            "check_id": cid,
            "description": desc,
            "expected": expected,
            "actual": actual,
            "passed": passed,
        }

    # C1: intact throughput in plausible range
    lo, hi = 9_000_000.0, 11_000_000.0
    checks.append(_row(
        1, "Intact throughput in [9M, 11M] TEU/yr",
        f"[{lo/1e6:.1f}M, {hi/1e6:.1f}M] TEU",
        f"{intact_teu/1e6:.3f}M TEU",
        lo <= intact_teu <= hi,
    ))

    # C2: all disrupted throughputs ≤ intact (equality is valid when disruption_days=0)
    # Tolerance: 1 TEU to handle CRN-induced floating-point exact equality
    _eps = 1.0
    violators = [r for r in disrupted if r.throughput_mean_teu > intact_teu + _eps]
    worst = min(disrupted, key=lambda r: r.throughput_mean_teu)
    checks.append(_row(
        2, "All 25 disrupted throughputs ≤ intact (0-day disruption scenarios may equal intact)",
        "disrupted_teu ≤ intact_teu + 1 TEU for all scenarios",
        (
            f"min disrupted = s{worst.scenario_id} at {worst.throughput_mean_teu/1e6:.3f}M TEU; "
            f"{len(violators)} scenarios strictly above intact (expect 0)"
        ),
        len(violators) == 0,
    ))

    # C3: monotone by typhoon category (same dist_bin=1, Cat1 < Cat2 < ... < Cat5 effect)
    bin1_by_cat = sorted(
        [r for r in disrupted if (r.scenario_id - 1) % 5 == 0],
        key=lambda r: (r.scenario_id - 1) // 5,
    )
    mono_cat = all(
        bin1_by_cat[i].throughput_mean_teu >= bin1_by_cat[i + 1].throughput_mean_teu
        for i in range(len(bin1_by_cat) - 1)
    )
    cat_vals = " > ".join(f"{r.throughput_mean_teu/1e6:.2f}M" for r in bin1_by_cat)
    checks.append(_row(
        3, "Monotone by typhoon category (bin1): Cat1 ≥ Cat2 ≥ ... ≥ Cat5 throughput",
        "throughput decreases as category increases",
        cat_vals,
        mono_cat,
    ))

    # C4: monotone by distance (Cat5, all bins): bin1 < bin2 < ... < bin5 throughput
    cat5 = sorted(
        [r for r in disrupted if (r.scenario_id - 1) // 5 == 4],
        key=lambda r: (r.scenario_id - 1) % 5,
    )
    mono_dist = all(
        cat5[i].throughput_mean_teu <= cat5[i + 1].throughput_mean_teu
        for i in range(len(cat5) - 1)
    )
    dist_vals = " < ".join(f"{r.throughput_mean_teu/1e6:.2f}M" for r in cat5)
    checks.append(_row(
        4, "Monotone by distance (Cat5): bin1 ≤ bin2 ≤ ... ≤ bin5 throughput",
        "throughput increases as distance increases (less impact far away)",
        dist_vals,
        mono_dist,
    ))

    # C5: intact CI half-width < 5% of mean
    ci_pct = intact_ci_hw / intact_teu if intact_teu > 0 else float("inf")
    checks.append(_row(
        5, "Intact CI half-width < 5% of mean",
        "CI_hw / mean < 0.05",
        f"{ci_pct*100:.3f}% ({intact_ci_hw:,.0f} TEU)",
        ci_pct < 0.05,
    ))

    # C6: intact served_ship_calls > 0
    checks.append(_row(
        6, "Intact served_ship_calls > 0",
        "served_ship_calls_mean > 0",
        f"{intact_calls:.1f} calls",
        intact_calls > 0,
    ))

    return checks


def vrf_summary(checks: list[dict]) -> dict:
    """Summarise VRF check list into pass/fail counts and overall verdict."""
    n_pass = sum(1 for c in checks if c["passed"])
    n_fail = len(checks) - n_pass
    return {
        "total_checks": len(checks),
        "passed": n_pass,
        "failed": n_fail,
        "vrf_passed": n_fail == 0,
    }


# ---------------------------------------------------------------------------
# VLD: sanity-check comparison against the benchmark reference
# ---------------------------------------------------------------------------

def run_vld_comparison(results: SimulationResults, tolerance_pct: float = 0.20) -> dict:
    """Compare intact simulation output against the benchmark reference (VLD —
    Validation: sanity check vs benchmark reference).

    Annualises the 7-month actual records (× 12/7) then computes:
        rel_error = (our_value - ref_annual) / ref_annual

    Args:
        results:       validated SimulationResults from E2
        tolerance_pct: relative tolerance for pass/fail (default 0.20 = ±20%).
                       Declare the value in design_simulation.md (VLD section); pass it
                       explicitly from the caller rather than relying on the default.

    Returns a dict with per-KPI comparison rows and an overall verdict.
    """
    ref_annual_ships = _BENCHMARK_SHIP_ARRIVALS_7MO * _ANNUALISE
    ref_annual_teu = _BENCHMARK_THROUGHPUT_TEU_7MO * _ANNUALISE

    our_ships = results.intact.served_ship_calls_mean
    our_teu = results.intact.throughput_mean_teu

    def _kpi_row(
        kpi: str,
        actual_7mo: float,
        ref_annual: float,
        our_value: float,
        unit: str,
    ) -> dict:
        rel_err = (our_value - ref_annual) / ref_annual if ref_annual > 0 else float("nan")
        return {
            "kpi":            kpi,
            "actual_7mo":     round(actual_7mo, 1),
            "ref_annual":     round(ref_annual, 1),
            "our_simulation": round(our_value, 1),
            "rel_error_pct":  round(rel_err * 100, 2),
            "tolerance_pct":  round(tolerance_pct * 100, 1),
            "within_tolerance": abs(rel_err) <= tolerance_pct,
            "unit":           unit,
        }

    kpis = [
        _kpi_row(
            "ship_arrivals",
            _BENCHMARK_SHIP_ARRIVALS_7MO,
            ref_annual_ships,
            our_ships,
            "calls/yr",
        ),
        _kpi_row(
            "throughput_teu",
            _BENCHMARK_THROUGHPUT_TEU_7MO,
            ref_annual_teu,
            our_teu,
            "TEU/yr",
        ),
    ]

    n_pass = sum(1 for k in kpis if k["within_tolerance"])
    return {
        "reference":      BENCHMARK_REF,
        "kpis":           kpis,
        "n_replications": results.n_replications_used,
        "tolerance_pct":  round(tolerance_pct * 100, 1),
        "all_passed":     n_pass == len(kpis),
        "note": (
            "VLD type: non-paired sanity check — reason: only single-period aggregate data available. "
            f"Pass = within ±{tolerance_pct*100:.0f}% of the annualised benchmark reference (×12/7). "
            "Annualised from a 7-month observation window."
        ),
    }

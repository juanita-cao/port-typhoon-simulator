"""Build per-scenario loss lookup from existing E2 output + E3 + E4 + E5.

One-time offline script. Reads the latest E2 run artifacts, runs E3/E4/E5,
and writes src/backend/configs/scenario_loss_lookup.json:

  {scenario_id (str): {
      "physical_mean_usd": float,
      "physical_p95_usd":  float,
      "economic_usd":      float,
      "total_usd":         float
  }, ...}

Used by E1 (e1_parse_ibtracs.py) to populate per-event loss estimates
in data/typhoon_history.json for the frontend Tab 2 historical table.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from backend.e_nodes import (
    _load_port_config,
    _load_scenario_matrix,
    e3_estimate_physical_loss,
    e4_estimate_economic_loss,
    e5_aggregate_losses,
)
from backend.schemas import SimRunResult, SimulationResults

OUTPUT_DIR  = ROOT / "outputs" / "latest"
LOOKUP_PATH = ROOT / "src" / "backend" / "configs" / "scenario_loss_lookup.json"


def main() -> None:
    # -----------------------------------------------------------------------
    # Load existing E2 output
    # -----------------------------------------------------------------------
    e2_path = OUTPUT_DIR / "e2_output.json"
    print(f"Loading E2 output from {e2_path}")
    raw = json.loads(e2_path.read_text())

    intact_data    = raw["intact"]
    disrupted_data = raw["disrupted"]

    intact = SimRunResult(**intact_data)
    disrupted = [SimRunResult(**s) for s in disrupted_data]
    sim_results = SimulationResults(
        intact=intact,
        disrupted=disrupted,
        n_replications_used=raw["n_replications_used"],
    )
    print(f"  intact throughput: {intact.throughput_mean_teu:,.0f} TEU/yr")
    print(f"  disrupted scenarios: {len(disrupted)}")

    # -----------------------------------------------------------------------
    # E3 — Physical loss (Monte Carlo, standalone, ~seconds)
    # -----------------------------------------------------------------------
    print("Running E3 (physical loss MC)…")
    physical = e3_estimate_physical_loss(
        port_name="NPT",
        n_mc_samples=10_000,
        random_seed_base=42,
        verbose=False,
        output_dir=None,
    )

    # -----------------------------------------------------------------------
    # E4 — Economic loss
    # -----------------------------------------------------------------------
    print("Running E4 (economic loss)…")
    economic = e4_estimate_economic_loss(
        sim_results,
        handling_charge_usd_per_teu=120.0,
        verbose=False,
        output_dir=None,
    )

    # -----------------------------------------------------------------------
    # E5 — Aggregate (builds per-scenario totals)
    # -----------------------------------------------------------------------
    print("Running E5 (aggregate)…")
    scenario_matrix = _load_scenario_matrix()
    port_config     = _load_port_config("NPT")
    loss_profile = e5_aggregate_losses(
        physical, economic, scenario_matrix, port_config,
        verbose=False, output_dir=None,
    )

    # -----------------------------------------------------------------------
    # Build lookup {scenario_id_str → losses}
    # -----------------------------------------------------------------------
    phys_by_id = {e.scenario_id: e for e in physical.estimates}
    econ_by_id = {e.scenario_id: e for e in economic.estimates}

    lookup: dict[str, dict] = {}
    for scen in loss_profile.scenario_losses:
        sid = scen.scenario_id
        p   = phys_by_id[sid]
        e   = econ_by_id[sid]
        lookup[str(sid)] = {
            "physical_mean_usd": round(p.loss_mean_usd),
            "physical_p95_usd":  round(p.loss_p95_usd),
            "economic_usd":      round(e.economic_loss_usd),
            "total_usd":         round(p.loss_mean_usd + e.economic_loss_usd),
        }

    LOOKUP_PATH.write_text(json.dumps(lookup, indent=2))
    print(f"\nWrote {LOOKUP_PATH}  ({len(lookup)} scenarios)")

    print("\n=== Loss lookup (total_usd) ===")
    for sid_str, v in sorted(lookup.items(), key=lambda x: int(x[0])):
        cat  = (int(sid_str) - 1) // 5 + 1
        dbin = (int(sid_str) - 1) %  5 + 1
        print(f"  scen {sid_str:2s}  Cat{cat} dist_bin{dbin}  "
              f"physical ${v['physical_mean_usd']/1e6:.1f}M  "
              f"econ ${v['economic_usd']/1e6:.1f}M  "
              f"total ${v['total_usd']/1e6:.1f}M")

    print(f"\nhistorical_total: ${loss_profile.historical_total_usd/1e6:.1f}M")
    print(f"predicted_5yr:    ${loss_profile.predicted_5yr_usd/1e6:.1f}M")


if __name__ == "__main__":
    main()

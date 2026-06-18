"""E1 preprocessing: build frontend data files from e1_load_typhoon_data().

One-time / occasional script (not called at runtime). Calls the live,
schema-validated E1 step (backend.e_nodes.e1_load_typhoon_data) to get the
qualifying storms + classified scenarios, then builds the frontend-specific
static files from that validated result — so there's a single source of
truth for the IBTrACS parsing + scenario-classification logic, and this
script is just a downstream consumer that caches it to disk for the
frontend to read without re-parsing the (large) IBTrACS CSV on every request.

Inputs:
  data/raw/ibtracs.WP.list.v04r01.csv          (IBTrACS v04r01, WP basin)
  src/backend/configs/scenario_loss_lookup.json (from build_scenario_loss_lookup.py)

Outputs:
  src/backend/configs/typhoon_presets.json   — curated dropdown list
  data/typhoon_tracks/{sid}.json             — per-storm track points for map animation
  data/typhoon_history.json                  — all qualifying events, for the historical-records tab
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from backend.e_nodes import e1_load_typhoon_data  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PORT_LAT = 21.800   # NPT — illustrative South China Sea coastal location (demo, not a real terminal)
PORT_LON = 113.100

STUDY_START = 1994
STUDY_END   = 2026   # extended to current year; IBTrACS v04r01 updated continuously

MAX_DIST_KM    = 500   # matches scenario matrix max dist_bin boundary
TRACK_BOX_KM   = 2000  # include track points within this radius for visualization

# Curated presets: diverse category × distance, well-known storms.
# (name.lower(), year) → preferred; script falls back if not found in parsed data.
_PREFERRED_PRESETS: list[tuple[str, int]] = [
    ("molave",    2009),  # Cat 1, ~15 km  — closest ever approach
    ("maggie",    1999),  # Cat 2, ~41 km  — close Cat 2
    ("usagi",     2013),  # Cat 3, ~60 km  — well-known Cat 3
    ("dujuan",    2003),  # Cat 4, ~46 km  — close Cat 4
    ("vicente",   2012),  # Cat 4, ~130 km — moderate-distance Cat 4
    ("mangkhut",  2018),  # Cat 5, direct close-range hit
    ("saola",     2023),  # recent close-range storm
    ("rammasun",  2014),  # Cat 5, ~425 km — distant Cat 5
]
PRESET_COUNT = 8  # target number of presets


def disruption_label(scenario: dict) -> str:
    lo = scenario["disruption_days_min"]
    hi = scenario["disruption_days_max"]
    if lo == hi:
        return f"{lo} days"
    return f"{lo}–{hi} days"


def main() -> None:
    csv_path     = ROOT / "data" / "raw" / "ibtracs.WP.list.v04r01.csv"
    tracks_dir   = ROOT / "data" / "typhoon_tracks"
    history_path = ROOT / "data" / "typhoon_history.json"
    presets_path = ROOT / "src" / "backend" / "configs" / "typhoon_presets.json"
    scenario_cfg = ROOT / "src" / "backend" / "configs" / "scenario_params.json"

    tracks_dir.mkdir(parents=True, exist_ok=True)

    scenario_data = json.loads(scenario_cfg.read_text())
    scenario_lookup = {s["scenario_id"]: s for s in scenario_data["scenarios"]}

    loss_lookup_path = ROOT / "src" / "backend" / "configs" / "scenario_loss_lookup.json"
    if loss_lookup_path.exists():
        loss_lookup: dict[str, dict] = json.loads(loss_lookup_path.read_text())
        print(f"Loaded loss lookup ({len(loss_lookup)} scenarios)")
    else:
        loss_lookup = {}
        print("WARNING: scenario_loss_lookup.json not found — loss_usd will be null")

    # -----------------------------------------------------------------------
    # E1 — the live, schema-validated step
    # -----------------------------------------------------------------------
    print(f"Running e1_load_typhoon_data on {csv_path} …")
    track_data = e1_load_typhoon_data(
        ibtracs_path=csv_path,
        port_lat=PORT_LAT,
        port_lon=PORT_LON,
        radius_km=MAX_DIST_KM,
        study_years=(STUDY_START, STUDY_END),
        track_box_km=TRACK_BOX_KM,
    )
    print(f"Qualifying typhoons (Cat ≥ 1, within {MAX_DIST_KM} km, "
          f"{STUDY_START}–{STUDY_END}): {track_data.total_event_count}")

    # -----------------------------------------------------------------------
    # Build the frontend-specific history list + per-storm track files
    # -----------------------------------------------------------------------
    history: list[dict] = []
    for event in track_data.events:
        scen = scenario_lookup[event.scenario_id]
        history.append({
            "sid":           event.storm_id,
            "name":          event.name,
            "year":          event.year,
            "display_name":  f"{event.name} {event.year}",
            "category":      event.saffir_simpson_cat,
            "strike_dist_km": event.min_distance_km,
            "dist_bin":      event.distance_bin,
            "scenario_id":   event.scenario_id,
            "disruption_days_min": scen["disruption_days_min"],
            "disruption_days_max": scen["disruption_days_max"],
            "disruption_label": disruption_label(scen),
            "loss_usd": loss_lookup.get(str(event.scenario_id), {}).get("total_usd"),
        })

        track_points = [
            {
                "lat": pt.lat,
                "lon": pt.lon,
                "time": pt.timestamp.strftime("%Y-%m-%dT%H:%M:%S"),
                "vmax_kt": pt.wind_speed_kt,
            }
            for pt in event.track_points
        ]
        track_path = tracks_dir / f"{event.storm_id}.json"
        track_path.write_text(json.dumps(track_points, separators=(",", ":")))

    history_path.write_text(json.dumps(history, indent=2))
    print(f"Wrote {history_path}")

    # -----------------------------------------------------------------------
    # Build typhoon_presets.json
    # -----------------------------------------------------------------------
    name_year_to_event: dict[tuple[str, int], dict] = {
        (e["name"].lower(), e["year"]): e for e in history
    }

    presets: list[dict] = []
    used_sids: set[str] = set()

    for name, year in _PREFERRED_PRESETS:
        key = (name.lower(), year)
        if key in name_year_to_event:
            e = name_year_to_event[key]
            if e["sid"] not in used_sids:
                presets.append(e)
                used_sids.add(e["sid"])
        if len(presets) >= PRESET_COUNT:
            break

    if len(presets) < PRESET_COUNT:
        remaining = sorted(
            [e for e in history if e["sid"] not in used_sids],
            key=lambda e: (-e["category"], e["strike_dist_km"]),
        )
        for e in remaining:
            presets.append(e)
            if len(presets) >= PRESET_COUNT:
                break

    presets.sort(key=lambda e: e["year"])
    presets_path.write_text(json.dumps(presets, indent=2))
    print(f"Wrote {presets_path}  ({len(presets)} presets)")

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    print("\n=== Preset Typhoons ===")
    for p in presets:
        print(f"  {p['display_name']:20s}  Cat {p['category']}  "
              f"{p['strike_dist_km']:6.1f} km  "
              f"scenario={p['scenario_id']}  "
              f"disruption: {p['disruption_label']}")

    print("\n=== All Historical Events ===")
    for e in history:
        loss_str = f"${e['loss_usd']/1e6:.1f}M" if e["loss_usd"] else "n/a"
        print(f"  {e['year']}  {e['name']:15s}  Cat {e['category']}  "
              f"{e['strike_dist_km']:6.1f} km  scenario={e['scenario_id']:2d}  loss={loss_str}")

    print(f"\nTrack files written to: {tracks_dir}")


if __name__ == "__main__":
    main()

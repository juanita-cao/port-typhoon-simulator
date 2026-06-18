"""E1: Parse IBTrACS WP basin CSV to produce frontend data files.

One-time preprocessing script (not called at runtime).

Inputs:
  data/raw/ibtracs.WP.list.v04r01.csv          (IBTrACS v04r01, WP basin)
  src/backend/configs/scenario_loss_lookup.json (from build_scenario_loss_lookup.py)

Outputs:
  src/backend/configs/typhoon_presets.json   — curated dropdown list (8 typhoons)
  data/typhoon_tracks/{sid}.json             — per-storm track points for map animation
                                               (extended with wind field: vmax_kt, rmw_nm,
                                                r34/r50/r64 per quadrant, cat per point)
  data/typhoon_history.json                  — all qualifying events (1994-present) for Tab 2

E1 extension (wind field):
  R34/R50/R64/RMW pulled from USA_* columns.
  Missing values filled by: linear interpolation along track → category-based default.
  Enables Holland (1980) parametric wind field for port risk heat map.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PORT_LAT = 21.800   # NPT — illustrative South China Sea coastal location (demo, not a real terminal)
PORT_LON = 113.100

STUDY_START = 1994
STUDY_END   = 2026   # extended to current year; IBTrACS v04r01 updated continuously

MAX_DIST_KM    = 500   # matches scenario matrix max dist_bin boundary
TRACK_BOX_KM   = 2000  # include track points within this radius for visualization

# ---------------------------------------------------------------------------
# Wind-field fill defaults (used when IBTrACS value is missing)
# Sources: literature averages (Knaff et al. 2014, Willoughby et al. 2006)
# ---------------------------------------------------------------------------
# RMW (nm) by Saffir-Simpson category
_CAT_RMW_NM:  dict[int, float] = {-1: 80, 0: 60, 1: 45, 2: 35, 3: 25, 4: 18, 5: 13}
# Vmax (kt) by category (mid-range of SS scale)
_CAT_VMAX_KT: dict[int, float] = {-1: 25, 0: 45, 1: 70, 2: 90, 3: 105, 4: 125, 5: 150}
# R34 symmetric default (nm) by category (rough average all quadrants)
_CAT_R34_NM:  dict[int, float] = {-1: 0, 0: 0, 1: 120, 2: 150, 3: 180, 4: 220, 5: 260}
# R50 symmetric default (nm) by category
_CAT_R50_NM:  dict[int, float] = {-1: 0, 0: 0, 1: 0,   2: 60,  3: 90,  4: 120, 5: 150}
# R64 symmetric default (nm) by category
_CAT_R64_NM:  dict[int, float] = {-1: 0, 0: 0, 1: 0,   2: 0,   3: 40,  4: 65,  5: 90}

# Distance bin boundaries (km) matching scenario_params.json
DIST_BINS = [100, 200, 300, 400, 500]   # upper boundary of each bin

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def dist_bin_for(dist_km: float) -> int:
    for i, upper in enumerate(DIST_BINS, start=1):
        if dist_km <= upper:
            return i
    return 5  # shouldn't happen if filtered to MAX_DIST_KM


def scenario_id_for(cat: int, dist_bin: int) -> int:
    return (cat - 1) * 5 + dist_bin


def _fill_wind_series(series: pd.Series, cat_series: pd.Series,
                       default_map: dict[int, float]) -> pd.Series:
    """Interpolate missing wind-field values; fall back to category default."""
    s = pd.to_numeric(series, errors="coerce")
    s = s.interpolate(method="linear", limit_direction="both")
    # Where still NaN, use category-based default
    mask = s.isna()
    if mask.any():
        cats = pd.to_numeric(cat_series, errors="coerce").fillna(1).astype(int).clip(-1, 5)
        s[mask] = cats[mask].map(lambda c: default_map.get(c, default_map[1]))
    return s.round(1)


def disruption_label(scenario: dict) -> str:
    lo = scenario["disruption_days_min"]
    hi = scenario["disruption_days_max"]
    if lo == hi:
        return f"{lo} days"
    return f"{lo}–{hi} days"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    root = Path(__file__).parent.parent
    csv_path     = root / "data" / "raw" / "ibtracs.WP.list.v04r01.csv"
    tracks_dir   = root / "data" / "typhoon_tracks"
    history_path = root / "data" / "typhoon_history.json"
    presets_path = root / "src" / "backend" / "configs" / "typhoon_presets.json"
    scenario_cfg = root / "src" / "backend" / "configs" / "scenario_params.json"

    tracks_dir.mkdir(parents=True, exist_ok=True)

    # Load scenario disruption params {scenario_id: {...}}
    with open(scenario_cfg) as f:
        scenario_data = json.load(f)
    scenario_lookup = {s["scenario_id"]: s for s in scenario_data["scenarios"]}

    # Load per-scenario loss estimates from build_scenario_loss_lookup.py output
    loss_lookup_path = root / "src" / "backend" / "configs" / "scenario_loss_lookup.json"
    if loss_lookup_path.exists():
        with open(loss_lookup_path) as f:
            loss_lookup: dict[str, dict] = json.load(f)
        print(f"Loaded loss lookup ({len(loss_lookup)} scenarios)")
    else:
        loss_lookup = {}
        print("WARNING: scenario_loss_lookup.json not found — loss_usd will be null")

    # -----------------------------------------------------------------------
    # Read IBTrACS CSV
    # -----------------------------------------------------------------------
    print(f"Reading {csv_path} …")
    _WIND_COLS = [
        "USA_WIND", "USA_RMW",
        "USA_R34_NE", "USA_R34_SE", "USA_R34_SW", "USA_R34_NW",
        "USA_R50_NE", "USA_R50_SE", "USA_R50_SW", "USA_R50_NW",
        "USA_R64_NE", "USA_R64_SE", "USA_R64_SW", "USA_R64_NW",
    ]
    df = pd.read_csv(
        csv_path,
        skiprows=[1],          # row 1 = units line
        na_values=[" ", ""],
        low_memory=False,
        usecols=["SID", "SEASON", "NAME", "ISO_TIME", "LAT", "LON",
                 "WMO_WIND", "USA_SSHS"] + _WIND_COLS,
        dtype={"SEASON": "Int64", "USA_SSHS": "Int64"},
    )

    # Filter to study period
    df = df[df["SEASON"].between(STUDY_START, STUDY_END)].copy()
    df["ISO_TIME"] = pd.to_datetime(df["ISO_TIME"], errors="coerce")
    df["LAT"] = pd.to_numeric(df["LAT"], errors="coerce")
    df["LON"] = pd.to_numeric(df["LON"], errors="coerce")
    df.dropna(subset=["LAT", "LON", "ISO_TIME"], inplace=True)

    print(f"Rows after study-period filter: {len(df):,}")

    # -----------------------------------------------------------------------
    # Compute distance from port for every track point
    # -----------------------------------------------------------------------
    df["dist_km"] = df.apply(
        lambda r: haversine_km(r["LAT"], r["LON"], PORT_LAT, PORT_LON), axis=1
    )

    # -----------------------------------------------------------------------
    # Identify qualifying storms
    # -----------------------------------------------------------------------
    history: list[dict] = []

    for sid, grp in df.groupby("SID"):
        grp_sorted = grp.sort_values("ISO_TIME")

        # Rows within MAX_DIST_KM
        near = grp_sorted[grp_sorted["dist_km"] <= MAX_DIST_KM]
        if near.empty:
            continue

        # Category: max USA_SSHS while near port
        cat_series = near["USA_SSHS"].dropna()
        if cat_series.empty:
            # Fall back to overall max USA_SSHS
            cat_series = grp_sorted["USA_SSHS"].dropna()
        if cat_series.empty:
            continue
        max_cat = int(cat_series.max())
        if max_cat < 1:
            continue  # tropical storm or weaker — skip

        min_dist = float(near["dist_km"].min())
        dbin = dist_bin_for(min_dist)
        sid_str = str(sid)
        name = str(grp_sorted["NAME"].iloc[0]).strip().title()
        year = int(grp_sorted["SEASON"].iloc[0])
        scen_id = scenario_id_for(max_cat, dbin)
        scen = scenario_lookup[scen_id]

        history.append({
            "sid":           sid_str,
            "name":          name,
            "year":          year,
            "display_name":  f"{name} {year}",
            "category":      max_cat,
            "strike_dist_km": round(min_dist, 1),
            "dist_bin":      dbin,
            "scenario_id":   scen_id,
            "disruption_days_min": scen["disruption_days_min"],
            "disruption_days_max": scen["disruption_days_max"],
            "disruption_label": disruption_label(scen),
            "loss_usd": loss_lookup.get(str(scen_id), {}).get("total_usd"),
        })

        # Write track file — all points within TRACK_BOX_KM
        track_rows = grp_sorted[grp_sorted["dist_km"] <= TRACK_BOX_KM].copy()

        # Fill wind field columns within this storm's track segment
        cat_col = pd.to_numeric(track_rows["USA_SSHS"], errors="coerce").fillna(1).clip(-1, 5)
        track_rows["_vmax"]   = _fill_wind_series(track_rows["USA_WIND"],   cat_col, _CAT_VMAX_KT)
        track_rows["_rmw"]    = _fill_wind_series(track_rows["USA_RMW"],    cat_col, _CAT_RMW_NM)
        track_rows["_r34_ne"] = _fill_wind_series(track_rows["USA_R34_NE"], cat_col, _CAT_R34_NM)
        track_rows["_r34_se"] = _fill_wind_series(track_rows["USA_R34_SE"], cat_col, _CAT_R34_NM)
        track_rows["_r34_sw"] = _fill_wind_series(track_rows["USA_R34_SW"], cat_col, _CAT_R34_NM)
        track_rows["_r34_nw"] = _fill_wind_series(track_rows["USA_R34_NW"], cat_col, _CAT_R34_NM)
        track_rows["_r50_ne"] = _fill_wind_series(track_rows["USA_R50_NE"], cat_col, _CAT_R50_NM)
        track_rows["_r50_se"] = _fill_wind_series(track_rows["USA_R50_SE"], cat_col, _CAT_R50_NM)
        track_rows["_r50_sw"] = _fill_wind_series(track_rows["USA_R50_SW"], cat_col, _CAT_R50_NM)
        track_rows["_r50_nw"] = _fill_wind_series(track_rows["USA_R50_NW"], cat_col, _CAT_R50_NM)
        track_rows["_r64_ne"] = _fill_wind_series(track_rows["USA_R64_NE"], cat_col, _CAT_R64_NM)
        track_rows["_r64_se"] = _fill_wind_series(track_rows["USA_R64_SE"], cat_col, _CAT_R64_NM)
        track_rows["_r64_sw"] = _fill_wind_series(track_rows["USA_R64_SW"], cat_col, _CAT_R64_NM)
        track_rows["_r64_nw"] = _fill_wind_series(track_rows["USA_R64_NW"], cat_col, _CAT_R64_NM)

        track_points = []
        for _, r in track_rows.iterrows():
            pt: dict = {
                "lat":    round(float(r["LAT"]), 4),
                "lon":    round(float(r["LON"]), 4),
                "time":   r["ISO_TIME"].strftime("%Y-%m-%dT%H:%M:%S"),
                "cat":    int(cat_col[r.name]) if not pd.isna(cat_col[r.name]) else 1,
                "vmax_kt": float(r["_vmax"]),
                "rmw_nm":  float(r["_rmw"]),
                "r34_ne":  float(r["_r34_ne"]),
                "r34_se":  float(r["_r34_se"]),
                "r34_sw":  float(r["_r34_sw"]),
                "r34_nw":  float(r["_r34_nw"]),
                "r50_ne":  float(r["_r50_ne"]),
                "r50_se":  float(r["_r50_se"]),
                "r50_sw":  float(r["_r50_sw"]),
                "r50_nw":  float(r["_r50_nw"]),
                "r64_ne":  float(r["_r64_ne"]),
                "r64_se":  float(r["_r64_se"]),
                "r64_sw":  float(r["_r64_sw"]),
                "r64_nw":  float(r["_r64_nw"]),
            }
            track_points.append(pt)

        track_path = tracks_dir / f"{sid_str}.json"
        with open(track_path, "w") as f:
            json.dump(track_points, f, separators=(",", ":"))

    history.sort(key=lambda e: e["year"])
    print(f"Qualifying typhoons (Cat ≥ 1, within {MAX_DIST_KM} km, {STUDY_START}–{STUDY_END}): {len(history)}")

    # -----------------------------------------------------------------------
    # Write typhoon_history.json
    # -----------------------------------------------------------------------
    with open(history_path, "w") as f:
        json.dump(history, f, indent=2)
    print(f"Wrote {history_path}")

    # -----------------------------------------------------------------------
    # Build typhoon_presets.json
    # -----------------------------------------------------------------------
    name_year_to_event: dict[tuple[str, int], dict] = {
        (e["name"].lower(), e["year"]): e for e in history
    }

    presets: list[dict] = []
    used_sids: set[str] = set()

    # Preferred (name, year) pairs first
    for name, year in _PREFERRED_PRESETS:
        key = (name.lower(), year)
        if key in name_year_to_event:
            e = name_year_to_event[key]
            if e["sid"] not in used_sids:
                presets.append(e)
                used_sids.add(e["sid"])
        if len(presets) >= PRESET_COUNT:
            break

    # Fill remaining slots: prefer higher-category events not yet included
    if len(presets) < PRESET_COUNT:
        remaining = sorted(
            [e for e in history if e["sid"] not in used_sids],
            key=lambda e: (-e["category"], e["strike_dist_km"]),
        )
        for e in remaining:
            presets.append(e)
            if len(presets) >= PRESET_COUNT:
                break

    # Sort by year for display
    presets.sort(key=lambda e: e["year"])

    with open(presets_path, "w") as f:
        json.dump(presets, f, indent=2)
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

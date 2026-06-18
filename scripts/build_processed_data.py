"""Build data/processed/berthing_log.csv from raw_data.xlsx (Vessel Performance Report).

Source: data/raw/raw_data.xlsx — sheet "2016", header at row 3 (0-indexed).
Provides all timing columns needed to fit idle_before, idle_after, crane_eff
without relying on paper constants.

Usage:
    conda run -n somr python scripts/build_processed_data.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT      = Path(__file__).parents[1]
RAW_EXCEL = ROOT / "data" / "raw" / "raw_data.xlsx"
OUT_CSV   = ROOT / "data" / "processed" / "berthing_log.csv"

_GROUP_RANGES = [
    (14,   999),
    (1000, 1999),
    (2000, 2999),
    (3000, 3999),
    (4000, 4999),
    (5000, 5999),
    (6010, 9999),
]


def _lpc_group(lpc: int) -> int:
    for g, (lo, hi) in enumerate(_GROUP_RANGES):
        if lo <= lpc <= hi:
            return g
    return -1


def _combine_dt(date_series: pd.Series, time_series: pd.Series) -> pd.Series:
    return pd.to_datetime(
        date_series.astype(str) + " " + time_series.astype(str),
        errors="coerce",
    )


def main() -> None:
    print(f"Reading {RAW_EXCEL} ...")
    raw = pd.read_excel(RAW_EXCEL, sheet_name="2016", header=3)
    print(f"  {len(raw)} rows loaded.")

    atb_dt      = _combine_dt(raw["ATB_Date"], raw["ATB_Time"])
    atd_dt      = _combine_dt(raw["ATD_Date"], raw["ATD_Time"])
    commence_dt = _combine_dt(raw["Commence Datetime_Date"], raw["Commence Datetime_Time"])
    complete_dt = _combine_dt(raw["Complete Datetime_Date"], raw["Complete Datetime_Time"])

    df = pd.DataFrame({
        "atb_datetime":         atb_dt,
        "atd_datetime":         atd_dt,
        "op_commence_datetime": commence_dt,
        "op_complete_datetime": complete_dt,
        "lpc":                  raw["TTL moves\n(Dis+Load+Re+Sh+HC)"].astype(int),
        "qc_count":             raw["Qc# SUM"].astype(int),
        "ops_time_hrs":         raw["OPS time\n(hrs)"].astype(float),
    })

    df = df.sort_values("atb_datetime").reset_index(drop=True)

    df["inter_arrival_hrs"] = df["atb_datetime"].diff().dt.total_seconds() / 3600

    df["idle_before_hrs"] = (
        (df["op_commence_datetime"] - df["atb_datetime"]).dt.total_seconds() / 3600
    )
    df["idle_after_hrs"] = (
        (df["atd_datetime"] - df["op_complete_datetime"]).dt.total_seconds() / 3600
    )
    # Per-crane efficiency: moves / (ops_time_hrs × num_cranes)
    df["crane_eff_moves_per_hr"] = df["lpc"] / (df["ops_time_hrs"] * df["qc_count"])

    df["lpc_group"] = df["lpc"].apply(_lpc_group)

    unknown = (df["lpc_group"] == -1).sum()
    if unknown:
        print(f"WARNING: {unknown} rows with LPC outside defined groups")

    neg_ib = (df["idle_before_hrs"] < 0).sum()
    neg_ia = (df["idle_after_hrs"] < 0).sum()
    if neg_ib or neg_ia:
        print(f"WARNING: {neg_ib} negative idle_before, {neg_ia} negative idle_after")

    df = df[[
        "atb_datetime", "atd_datetime",
        "op_commence_datetime", "op_complete_datetime",
        "inter_arrival_hrs",
        "lpc", "qc_count", "lpc_group",
        "ops_time_hrs",
        "idle_before_hrs", "idle_after_hrs",
        "crane_eff_moves_per_hr",
    ]]

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False)
    print(f"Saved {len(df)} rows → {OUT_CSV}")

    print("\nKey stats:")
    for col in ["inter_arrival_hrs", "idle_before_hrs", "idle_after_hrs", "crane_eff_moves_per_hr"]:
        s = df[col].dropna()
        s = s[s > 0]
        print(f"  {col}: n={len(s)}, mean={s.mean():.3f}, std={s.std():.3f}")

    print("\nLPC group distribution:")
    grp = df.groupby("lpc_group").agg(n=("lpc", "count"))
    grp["pct"] = (grp["n"] / len(df) * 100).round(2)
    print(grp.to_string())


if __name__ == "__main__":
    main()

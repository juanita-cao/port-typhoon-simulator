"""Generate a synthetic vessel-call log to replace the original confidential
terminal dataset, so the rest of the data pipeline (build_processed_data.py ->
fit_input_distributions.py) can run end-to-end on shareable data.

The original portfolio source used a real container terminal's 2016 vessel
performance report. That dataset is not redistributable, so this script
fabricates a vessel-call log with the same column layout and a similar order
of magnitude (call volume, crane counts, timing) using parameters chosen for
this demo -- not the original fitted values.

Output: data/raw/raw_data.xlsx, sheet "2016", header row 3 (matches the
layout build_processed_data.py expects from the original report).

Usage:
    conda run -n somr python scripts/generate_synthetic_demo_data.py
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parents[1]
OUT_XLSX = ROOT / "data" / "raw" / "raw_data.xlsx"

N_SHIPS = 2860
SEED = 20260618

# Demo-chosen generation parameters (deliberately different from any
# previously fitted real-data values -- these just need to produce a
# plausible-looking vessel-call log, not reproduce a specific dataset).
MEAN_INTER_ARRIVAL_HRS = 2.10
GROUP_RANGES = [
    (14, 999), (1000, 1999), (2000, 2999),
    (3000, 3999), (4000, 4999), (5000, 5999), (6010, 9999),
]
GROUP_PROBS = [0.44, 0.32, 0.14, 0.06, 0.025, 0.0075, 0.0075]  # groups 5/6 kept rare (n<30) to exercise the small-sample fallback rule
GROUP_QC_MEAN = [3, 5, 6, 7, 8, 8, 9]
CRANE_EFF_MEAN = 19.0
CRANE_EFF_STD = 4.5
IDLE_BEFORE_MEAN_HRS = 0.60
IDLE_AFTER_MEAN_HRS = 0.90


def main() -> None:
    rng = np.random.default_rng(SEED)

    group_idx = rng.choice(len(GROUP_RANGES), size=N_SHIPS, p=GROUP_PROBS)
    lpc = np.empty(N_SHIPS, dtype=int)
    qc_count = np.empty(N_SHIPS, dtype=int)
    for i, g in enumerate(group_idx):
        lo, hi = GROUP_RANGES[g]
        lpc[i] = int(lo + (hi - lo) * rng.beta(2.0, 5.0))
        qc_count[i] = max(1, int(round(rng.normal(GROUP_QC_MEAN[g], 0.6))))

    crane_eff = np.clip(rng.normal(CRANE_EFF_MEAN, CRANE_EFF_STD, N_SHIPS), 2.0, None)
    ops_time_hrs = lpc / (qc_count * crane_eff)

    inter_arrival_hrs = rng.exponential(MEAN_INTER_ARRIVAL_HRS, N_SHIPS)
    idle_before_hrs = rng.lognormal(mean=np.log(IDLE_BEFORE_MEAN_HRS), sigma=0.8, size=N_SHIPS)
    idle_after_hrs = rng.lognormal(mean=np.log(IDLE_AFTER_MEAN_HRS), sigma=0.7, size=N_SHIPS)

    base = datetime(2016, 1, 1, 0, 0)
    atb_dt = []
    t = base
    for h in inter_arrival_hrs:
        t = t + timedelta(hours=float(h))
        atb_dt.append(t)

    commence_dt = [t + timedelta(hours=float(ib)) for t, ib in zip(atb_dt, idle_before_hrs, strict=False)]
    complete_dt = [t + timedelta(hours=float(o)) for t, o in zip(commence_dt, ops_time_hrs, strict=False)]
    atd_dt = [t + timedelta(hours=float(ia)) for t, ia in zip(complete_dt, idle_after_hrs, strict=False)]

    def split(dts: list[datetime]) -> tuple[list[str], list[str]]:
        return (
            [d.strftime("%Y-%m-%d") for d in dts],
            [d.strftime("%H:%M:%S") for d in dts],
        )

    atb_date, atb_time = split(atb_dt)
    atd_date, atd_time = split(atd_dt)
    comm_date, comm_time = split(commence_dt)
    comp_date, comp_time = split(complete_dt)

    df = pd.DataFrame({
        "ATB_Date": atb_date,
        "ATB_Time": atb_time,
        "ATD_Date": atd_date,
        "ATD_Time": atd_time,
        "Commence Datetime_Date": comm_date,
        "Commence Datetime_Time": comm_time,
        "Complete Datetime_Date": comp_date,
        "Complete Datetime_Time": comp_time,
        "TTL moves\n(Dis+Load+Re+Sh+HC)": lpc,
        "Qc# SUM": qc_count,
        "OPS time\n(hrs)": np.round(ops_time_hrs, 3),
    })

    OUT_XLSX.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(OUT_XLSX, engine="openpyxl") as writer:
        # 3 blank rows above the header so header=3 (0-indexed) lands correctly,
        # matching the layout build_processed_data.py expects.
        pd.DataFrame([["Synthetic demo data — generated for public portfolio"], [], []]).to_excel(
            writer, sheet_name="2016", header=False, index=False, startrow=0
        )
        df.to_excel(writer, sheet_name="2016", index=False, startrow=3)

    print(f"Saved {len(df)} synthetic vessel calls -> {OUT_XLSX}")


if __name__ == "__main__":
    main()

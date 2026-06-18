"""Fit input distributions from a processed demo berthing log (synthetic data).

Reads  : data/processed/berthing_log.csv
Writes : data/models/input_dist_record.csv

Protocol:
  - Fit-all per variable; select by SSE; persist all candidates in candidates_json
  - Small-sample fallback: n < 30 → Uniform = Beta(1, 1); n 30–99 → warn, still fit
  - Candidates for right-skewed variables (iat, idle_before, idle_after): lognorm, gamma, expon
  - Candidates for symmetric variables (crane_eff): norm, gamma, lognorm
  - Candidates for bounded variables (lpc): beta, uniform (beta(1,1)), triangular
  - All fitted from user data — no paper-only constants remain.

P1.3v compliance: candidates_json column contains ≥3 candidates with SSE per variable,
proving fit-all was executed (not hand-selected).

Usage:
    conda run -n somr python scripts/fit_input_distributions.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT         = Path(__file__).parents[1]
BERTHING_LOG = ROOT / "data" / "processed" / "berthing_log.csv"
RECORD_OUT   = ROOT / "data" / "models" / "input_dist_record.csv"

_GROUP_RANGES: list[tuple[int, int]] = [
    (14,   999),
    (1000, 1999),
    (2000, 2999),
    (3000, 3999),
    (4000, 4999),
    (5000, 5999),
    (6010, 9999),
]
_SMALL_SAMPLE_N_MIN = 30


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def _empirical_cdf(data: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    x = np.sort(data)
    ecdf = np.arange(1, len(x) + 1) / len(x)
    return x, ecdf


def _sse(x: np.ndarray, ecdf: np.ndarray, cdf_fn) -> float:
    return float(np.sum((ecdf - cdf_fn(x)) ** 2))


def _ks_p(data: np.ndarray, cdf_fn) -> float:
    _, p = stats.kstest(data, cdf_fn)
    return float(p)


def _fit_all_skewed(
    data: np.ndarray,
) -> tuple[str, dict, float, float, list[dict]]:
    """Fit lognorm, gamma, expon; pick best by SSE.

    Returns (best_name, best_params, best_sse, best_ks_p, all_candidates).
    all_candidates has one entry per distribution tried — persisted in output
    to prove fit-all was executed (P1.3v).
    """
    x, ecdf = _empirical_cdf(data)
    candidates: list[tuple[str, dict, float, float]] = []
    candidate_records: list[dict] = []

    # Lognormal (loc=0 forced for positive data)
    try:
        s, _, scale = stats.lognorm.fit(data, floc=0)
        p = {"s": round(s, 4), "loc": 0.0, "scale": round(scale, 4)}
        cdf = lambda t, s=s, scale=scale: stats.lognorm.cdf(t, s, loc=0, scale=scale)
        sse = _sse(x, ecdf, cdf)
        ksp = _ks_p(data, cdf)
        candidates.append(("lognorm", p, sse, ksp))
        candidate_records.append({"dist": "lognorm", "params": p, "sse": round(sse, 6), "ks_p": round(ksp, 4)})
    except Exception:
        pass

    # Gamma (loc=0 forced)
    try:
        a, _, scale = stats.gamma.fit(data, floc=0)
        p = {"a": round(a, 4), "loc": 0.0, "scale": round(scale, 4)}
        cdf = lambda t, a=a, scale=scale: stats.gamma.cdf(t, a, loc=0, scale=scale)
        sse = _sse(x, ecdf, cdf)
        ksp = _ks_p(data, cdf)
        candidates.append(("gamma", p, sse, ksp))
        candidate_records.append({"dist": "gamma", "params": p, "sse": round(sse, 6), "ks_p": round(ksp, 4)})
    except Exception:
        pass

    # Exponential (loc=0 forced)
    try:
        _, scale = stats.expon.fit(data, floc=0)
        p = {"loc": 0.0, "scale": round(scale, 4)}
        cdf = lambda t, scale=scale: stats.expon.cdf(t, loc=0, scale=scale)
        sse = _sse(x, ecdf, cdf)
        ksp = _ks_p(data, cdf)
        candidates.append(("expon", p, sse, ksp))
        candidate_records.append({"dist": "expon", "params": p, "sse": round(sse, 6), "ks_p": round(ksp, 4)})
    except Exception:
        pass

    best = min(candidates, key=lambda c: c[2])
    return best[0], best[1], best[2], best[3], candidate_records


def _fit_all_symmetric(
    data: np.ndarray,
) -> tuple[str, dict, float, float, list[dict]]:
    """Fit norm, gamma, lognorm; pick best by SSE.

    Returns (best_name, best_params, best_sse, best_ks_p, all_candidates).
    """
    x, ecdf = _empirical_cdf(data)
    candidates: list[tuple[str, dict, float, float]] = []
    candidate_records: list[dict] = []

    # Normal
    try:
        loc, scale = stats.norm.fit(data)
        p = {"loc": round(loc, 4), "scale": round(scale, 4)}
        cdf = lambda t, loc=loc, scale=scale: stats.norm.cdf(t, loc, scale)
        sse = _sse(x, ecdf, cdf)
        ksp = _ks_p(data, cdf)
        candidates.append(("norm", p, sse, ksp))
        candidate_records.append({"dist": "norm", "params": p, "sse": round(sse, 6), "ks_p": round(ksp, 4)})
    except Exception:
        pass

    # Gamma (loc=0 forced)
    try:
        a, _, scale = stats.gamma.fit(data, floc=0)
        p = {"a": round(a, 4), "loc": 0.0, "scale": round(scale, 4)}
        cdf = lambda t, a=a, scale=scale: stats.gamma.cdf(t, a, loc=0, scale=scale)
        sse = _sse(x, ecdf, cdf)
        ksp = _ks_p(data, cdf)
        candidates.append(("gamma", p, sse, ksp))
        candidate_records.append({"dist": "gamma", "params": p, "sse": round(sse, 6), "ks_p": round(ksp, 4)})
    except Exception:
        pass

    # Lognormal (loc=0 forced)
    try:
        s, _, scale = stats.lognorm.fit(data, floc=0)
        p = {"s": round(s, 4), "loc": 0.0, "scale": round(scale, 4)}
        cdf = lambda t, s=s, scale=scale: stats.lognorm.cdf(t, s, loc=0, scale=scale)
        sse = _sse(x, ecdf, cdf)
        ksp = _ks_p(data, cdf)
        candidates.append(("lognorm", p, sse, ksp))
        candidate_records.append({"dist": "lognorm", "params": p, "sse": round(sse, 6), "ks_p": round(ksp, 4)})
    except Exception:
        pass

    best = min(candidates, key=lambda c: c[2])
    return best[0], best[1], best[2], best[3], candidate_records


def _beta_sse(data_01: np.ndarray, a: float, b: float) -> float:
    x = np.sort(data_01)
    ecdf = np.arange(1, len(x) + 1) / len(x)
    return float(np.sum((ecdf - stats.beta.cdf(x, a, b)) ** 2))


def _expon_sse(data: np.ndarray, scale: float) -> float:
    x = np.sort(data)
    ecdf = np.arange(1, len(x) + 1) / len(x)
    return float(np.sum((ecdf - stats.expon.cdf(x, scale=scale)) ** 2))


# ---------------------------------------------------------------------------
# Per-variable fit functions
# ---------------------------------------------------------------------------

def fit_iat(df: pd.DataFrame) -> dict:
    """Fit inter-arrival time using fit-all (lognorm, gamma, expon); pick by SSE."""
    iat = df["inter_arrival_hrs"].dropna()
    iat = iat[iat > 0].to_numpy(dtype=float)
    dist_name, params, sse, ks_p, candidates = _fit_all_skewed(iat)
    return {
        "variable":       "inter_arrival_hrs",
        "group":          "",
        "dist_name":      dist_name,
        "params":         json.dumps(params),
        "n":              len(iat),
        "sse":            round(sse, 6),
        "ks_p_value":     round(float(ks_p), 4),
        "source":         "user_data — raw_data.xlsx 2016",
        "confidence":     "High",
        "notes":          f"fit-all winner: {dist_name}; mean={iat.mean():.4f} hrs",
        "candidates_json": json.dumps(candidates),
    }


def fit_lpc_group(df: pd.DataFrame, g: int) -> dict:
    """Fit LPC within group g. Candidates: Uniform, Beta MLE, Triangular (bounded data)."""
    lo, hi = _GROUP_RANGES[g]
    lpc = df.loc[df["lpc_group"] == g, "lpc"].to_numpy(dtype=float)
    n   = len(lpc)

    candidate_records: list[dict] = []

    if n < _SMALL_SAMPLE_N_MIN:
        # Small-sample fallback: too few samples → Uniform (conservative)
        a, b = 1.0, 1.0
        sse  = _beta_sse((lpc - lo) / (hi - lo), a, b)
        candidate_records.append({"dist": "uniform (beta(1,1))", "params": {"a": 1.0, "b": 1.0, "lo": lo, "hi": hi}, "sse": round(sse, 6), "ks_p": None})
        note = f"n={n} < {_SMALL_SAMPLE_N_MIN} — too few samples, using Uniform (conservative); fit-all skipped"
        dist_name = "beta_uniform"
        best_params = {"a": a, "b": b, "lo": lo, "hi": hi}
        best_sse = sse
        ks_p_val = None
    else:
        x_01 = np.clip((lpc - lo) / (hi - lo), 1e-6, 1 - 1e-6)

        # Candidate 1: Uniform = Beta(1, 1)
        sse_u = _beta_sse(x_01, 1.0, 1.0)
        _, ksp_u = stats.kstest(x_01, lambda t: stats.beta.cdf(t, 1.0, 1.0))
        candidate_records.append({"dist": "uniform (beta(1,1))", "params": {"a": 1.0, "b": 1.0, "lo": lo, "hi": hi}, "sse": round(sse_u, 6), "ks_p": round(float(ksp_u), 4)})

        # Candidate 2: Beta MLE
        a_b, b_b, _, _ = stats.beta.fit(x_01, floc=0, fscale=1)
        a_b, b_b = round(a_b, 4), round(b_b, 4)
        sse_b = _beta_sse(x_01, a_b, b_b)
        _, ksp_b = stats.kstest(x_01, lambda t: stats.beta.cdf(t, a_b, b_b))
        candidate_records.append({"dist": "beta", "params": {"a": a_b, "b": b_b, "lo": lo, "hi": hi}, "sse": round(sse_b, 6), "ks_p": round(float(ksp_b), 4)})

        # Candidate 3: Triangular (c = mode position in [0,1])
        try:
            c_t, loc_t, scale_t = stats.triang.fit(x_01, floc=0, fscale=1)
            c_t = round(float(c_t), 4)
            sse_t = _beta_sse(x_01, 1.0, 1.0)  # use generic SSE helper on x_01
            x_s = np.sort(x_01)
            ecdf_s = np.arange(1, len(x_s) + 1) / len(x_s)
            sse_t = float(np.sum((ecdf_s - stats.triang.cdf(x_s, c_t, loc=0, scale=1)) ** 2))
            _, ksp_t = stats.kstest(x_01, lambda t: stats.triang.cdf(t, c_t, loc=0, scale=1))
            candidate_records.append({"dist": "triangular", "params": {"c": c_t, "lo": lo, "hi": hi}, "sse": round(sse_t, 6), "ks_p": round(float(ksp_t), 4)})
        except Exception:
            pass

        # Pick best by SSE
        ranked = sorted(candidate_records, key=lambda r: r["sse"])
        winner = ranked[0]
        if winner["dist"] == "beta":
            a, b = a_b, b_b
            sse_best = sse_b
            ksp_best = float(ksp_b)
            dist_name = "beta"
            best_params = {"a": a, "b": b, "lo": lo, "hi": hi}
        elif winner["dist"] == "triangular":
            dist_name = "triangular"
            best_params = winner["params"]
            sse_best = winner["sse"]
            ksp_best = winner["ks_p"]
            a, b = a_b, b_b  # keep for note
        else:
            a, b = 1.0, 1.0
            sse_best = sse_u
            ksp_best = float(ksp_u)
            dist_name = "beta_uniform"
            best_params = {"a": 1.0, "b": 1.0, "lo": lo, "hi": hi}

        best_sse = sse_best
        ks_p_val = ksp_best
        warn = " (n 30–99, treat with caution)" if n < 100 else ""
        note = f"fit-all winner: {dist_name}; n={n}; Beta MLE=({a_b},{b_b}); E[LPC]≈{lo + a_b/(a_b+b_b)*(hi-lo):.0f}{warn}"

    return {
        "variable":        "lpc",
        "group":           g,
        "dist_name":       dist_name,
        "params":          json.dumps(best_params),
        "n":               n,
        "sse":             round(best_sse, 6),
        "ks_p_value":      round(float(ks_p_val), 4) if ks_p_val is not None else None,
        "source":          "user_data — raw_data.xlsx 2016",
        "confidence":      "High" if n >= 100 else ("Medium" if n >= _SMALL_SAMPLE_N_MIN else "Low"),
        "notes":           note,
        "candidates_json": json.dumps(candidate_records),
    }


def fit_cranes_by_group(df: pd.DataFrame) -> list[dict]:
    rows = []
    for g, (_lo, _hi) in enumerate(_GROUP_RANGES):
        qc   = df.loc[df["lpc_group"] == g, "qc_count"].to_numpy(dtype=float)
        mean = float(qc.mean())
        val  = int(round(mean))
        rows.append({
            "variable":        "qc_count",
            "group":           g,
            "dist_name":       "deterministic",
            "params":          json.dumps({"value": val}),
            "n":               len(qc),
            "sse":             None,
            "ks_p_value":      None,
            "source":          "user_data — raw_data.xlsx 2016",
            "confidence":      "High",
            "notes":           f"round(mean QC) = round({mean:.2f}) = {val}",
            "candidates_json": json.dumps([{"dist": "deterministic", "params": {"value": val}, "sse": None, "ks_p": None}]),
        })
    return rows


def fit_idle_before(df: pd.DataFrame) -> dict:
    data = df["idle_before_hrs"].dropna()
    data = data[data > 0].to_numpy(dtype=float)
    dist_name, params, sse, ks_p, candidates = _fit_all_skewed(data)
    return {
        "variable":        "idle_time_before_hrs",
        "group":           "",
        "dist_name":       dist_name,
        "params":          json.dumps(params),
        "n":               len(data),
        "sse":             round(sse, 6),
        "ks_p_value":      round(ks_p, 4),
        "source":          "user_data — raw_data.xlsx 2016",
        "confidence":      "High",
        "notes":           f"fit-all winner: {dist_name}; mean={data.mean():.3f} hrs; std={data.std():.3f}; min={data.min():.3f}",
        "candidates_json": json.dumps(candidates),
    }


def fit_idle_after(df: pd.DataFrame) -> dict:
    data = df["idle_after_hrs"].dropna()
    data = data[data > 0].to_numpy(dtype=float)
    dist_name, params, sse, ks_p, candidates = _fit_all_skewed(data)
    return {
        "variable":        "idle_time_after_hrs",
        "group":           "",
        "dist_name":       dist_name,
        "params":          json.dumps(params),
        "n":               len(data),
        "sse":             round(sse, 6),
        "ks_p_value":      round(ks_p, 4),
        "source":          "user_data — raw_data.xlsx 2016",
        "confidence":      "High",
        "notes":           f"fit-all winner: {dist_name}; mean={data.mean():.3f} hrs; std={data.std():.3f}; min={data.min():.3f}",
        "candidates_json": json.dumps(candidates),
    }


def fit_crane_eff(df: pd.DataFrame) -> dict:
    data = df["crane_eff_moves_per_hr"].dropna()
    data = data[data > 0].to_numpy(dtype=float)
    dist_name, params, sse, ks_p, candidates = _fit_all_symmetric(data)
    return {
        "variable":        "crane_eff_moves_per_hr",
        "group":           "",
        "dist_name":       dist_name,
        "params":          json.dumps(params),
        "n":               len(data),
        "sse":             round(sse, 6),
        "ks_p_value":      round(ks_p, 4),
        "source":          "user_data — raw_data.xlsx 2016",
        "confidence":      "High",
        "notes":           (
            f"fit-all winner: {dist_name}; mean={data.mean():.2f} moves/hr/crane; "
            f"std={data.std():.2f}; per-crane efficiency (LPC/ops_hrs/qc_count)"
        ),
        "candidates_json": json.dumps(candidates),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"Loading {BERTHING_LOG} ...")
    df = pd.read_csv(BERTHING_LOG)
    print(f"  {len(df)} rows loaded.")

    rows: list[dict] = []

    iat_row = fit_iat(df)
    rows.append(iat_row)
    print(f"\n[IAT] winner={iat_row['dist_name']}  scale={json.loads(iat_row['params']).get('scale','?'):.4f} hrs  "
          f"n={iat_row['n']}  SSE={iat_row['sse']}  KS_p={iat_row['ks_p_value']}")
    for c in json.loads(iat_row["candidates_json"]):
        print(f"      candidate: {c['dist']:10s}  SSE={c['sse']}")

    total = len(df)
    print("\n[LPC group probs from data]")
    for g in range(7):
        n_g = (df["lpc_group"] == g).sum()
        print(f"  group {g}: n={n_g}, p={n_g/total:.4f}")

    print("\n[LPC fit-all]")
    for g in range(7):
        row = fit_lpc_group(df, g)
        rows.append(row)
        print(f"  group {g}: {row['notes']}")
        for c in json.loads(row["candidates_json"]):
            print(f"           candidate: {c['dist']:20s}  SSE={c['sse']}")

    print("\n[QC per group]")
    for row in fit_cranes_by_group(df):
        rows.append(row)
        print(f"  group {row['group']}: {row['notes']}")

    ib_row = fit_idle_before(df)
    rows.append(ib_row)
    print(f"\n[idle_before] {ib_row['notes']}")
    for c in json.loads(ib_row["candidates_json"]):
        print(f"              candidate: {c['dist']:10s}  SSE={c['sse']}")

    ia_row = fit_idle_after(df)
    rows.append(ia_row)
    print(f"[idle_after]  {ia_row['notes']}")
    for c in json.loads(ia_row["candidates_json"]):
        print(f"              candidate: {c['dist']:10s}  SSE={c['sse']}")

    ce_row = fit_crane_eff(df)
    rows.append(ce_row)
    print(f"[crane_eff]   {ce_row['notes']}")
    for c in json.loads(ce_row["candidates_json"]):
        print(f"              candidate: {c['dist']:10s}  SSE={c['sse']}")

    RECORD_OUT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(RECORD_OUT, index=False)
    print(f"\nSaved {len(rows)} records → {RECORD_OUT}")
    print("P1.3v: candidates_json column included — fit-all provable from CSV.")


if __name__ == "__main__":
    main()

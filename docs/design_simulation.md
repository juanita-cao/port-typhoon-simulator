# port_typhoon_simulator — Simulation Design Document

> Maps to `design_backend.md`'s E2 step (`e2_run_simulation`) — a stochastic discrete-event simulation, the one step in the pipeline with random side effects.
> Methodology: discrete-event simulation validated using Welch's (1983) warm-up method, Kelton's (2002) replication-count formula, common random numbers (CRN) for paired comparisons, and Holm-Bonferroni-corrected paired t-tests with effect sizes — the standard toolkit for rigorous simulation output analysis.

---

## 1. Purpose and scope

**Purpose:** across 26 scenarios (1 intact baseline + 25 typhoon-disruption scenarios), estimate the demo terminal's annual container throughput (TEU/year), which feeds the economic-loss calculation (E4) and the statistical-significance analysis below (§7).

**KPIs:**

| KPI | Definition | Unit | Direction |
|-----|------------|------|-----------|
| `throughput_teu` | total container volume handled per replication | TEU/year | higher is better |
| `served_ship_calls` | vessel calls completed (including departure) per replication | calls/year | higher is better |

> `teu_per_call = lpc × 1.75`. The 1.75 TEU-per-crane-lift factor reflects a typical mix of 40ft (2 TEU) and 20ft (1 TEU) containers at modern terminals, averaging roughly 1.75 TEU per lift. `lpc` (lifts per call) drives service time; `teu_per_call` drives the throughput count — the two are kept separate throughout.

**Out of scope:**
- physical loss estimation (E3)
- economic loss calculation (E4)
- typhoon track parsing and scenario-matrix construction (E1)
- supply-chain effects outside the port queue (not simulated)

**Pipeline position:** `E1 (load_typhoon_data) → E2 (run_simulation) → E3/E4/E5`. E2 outputs `SimulationResults` to E4.

### 1.1 Practical-significance thresholds

| KPI | Threshold (%) | Min effect size (dz) | Rationale |
|-----|---------|--------|------|
| `throughput_teu` | 5 | 0.2 | The smallest throughput change an operator would actually notice or act on — roughly 1–2 days of disrupted operation |

`operationally_meaningful` requires **both**: `relative_diff_pct >= 5.0` and `abs(cohens_dz) >= 0.2`. If either fails, the scenario is not flagged as meaningful even if it's statistically significant — see §7 for why that distinction matters.

---

## 2. Concept model

### 2.1 Entities

| Entity / Resource | Type | Input parameters | Output KPIs |
|-----------------|------|----------------|----------------|
| Ship | Entity | inter-arrival time, LPC group, LPC, cranes allocated | **throughput_teu**, **served_ship_calls** |
| Berth | Resource | capacity = `num_berths` | — |
| Quay crane | Resource pool | capacity = `num_quay_cranes`; drops to 0 during a disruption | — |
| Disruption event | Event | start time, duration, complete closure | — |

**Key modeling assumptions:**
- Ship arrivals: a Poisson process — inter-arrival times are exponentially distributed, fitted from the (synthetic, see §3) vessel-call log.
- Crane allocation: assigned by LPC-group probability, not a fixed count per berth — larger cargo calls get more cranes.
- Service time = idle-before + `lpc / (cranes × crane_efficiency)` + idle-after, all in hours.
- Disruption: complete closure (an Arena "Failure data"-equivalent model) — cranes are fully unavailable for the entire disruption+recovery window, then fully restored.
- Simulation type: **steady-state**. The port runs 24/7/365 with no natural termination event; the 365-day horizon is an observation window, not a stopping condition. Starting from an empty port introduces a startup bias, so a warm-up period is required (§4).

### 2.2 Entity attributes

```
Ship
  ├── arrival_time_hr: float       # simulation clock, hours
  ├── lpc_group: int                # 0–6, sampled by group probability
  ├── lpc: int                      # lifts for this call, sampled within the group's Beta distribution
  ├── cranes_allocated: int         # sampled by group mean
  ├── idle_before_hr: float         # wait before service starts (fitted lognormal)
  ├── service_time_hr: float        # lpc / (cranes × crane_eff_lifts_per_hr)
  ├── idle_after_hr: float          # wait after service ends (fitted lognormal)
  ├── total_berth_time_hr: float    # idle_before + service_time + idle_after
  ├── berth_wait_hr: float          # queueing time for a berth
  └── departure_time_hr: float

Port
  ├── num_berths: int
  ├── num_quay_cranes: int
  └── crane_eff_lifts_per_hr: float  # fitted normal, see §3

DisruptionEvent
  ├── start_hr: float               # sampled uniformly after warm-up
  ├── duration_hr: float            # disruption_days × 24, from the scenario config
  └── complete_closure: bool        # always True
```

### 2.3 Simulation flow

```
[Disruption process — parallel coroutine]
  ├── start_hr = uniform(warm_up_hrs, sim_horizon_hrs - duration_hr)
  ├── yield env.timeout(start_hr)
  ├── port.cranes._capacity = 0     ← demo implementation: mutate the SimPy Resource's capacity directly
  ├── yield env.timeout(duration_hr)
  └── port.cranes._capacity = num_quay_cranes   ← full restoration

  Ships arriving during a disruption queue for cranes; once the disruption ends,
  queued ships acquire cranes and begin service in order.

[Ship arrival process]  inter_arrival ~ fitted exponential
    ↓
◇ before warm-up? ──Y──→ [arrives, but excluded from stats]
    N
    ↓
◇ berth available? ──N──→ [queue for a berth]
    Y
    ↓
[assign berth]
    ↓
◇ cranes available? ──N──→ [queue for cranes — blocked during a disruption]
    Y
    ↓
[sample lpc_group, lpc, cranes_allocated, crane_efficiency, idle_before, idle_after]
[service_hr = lpc / (cranes × crane_eff)]
[total_hr = idle_before + service_hr + idle_after]
    ↓
[yield env.timeout(total_hr)]
    ↓
[record throughput += lpc × 1.75;  record served_ship_calls += 1]
    ↓
[release berth + cranes]  →  [ship departs]
```

---

## 3. Input data

### 3.1 Source and confidence

The original portfolio source used a real container terminal's confidential 2016 vessel performance report. That dataset isn't redistributable, so this public version uses **`scripts/generate_synthetic_demo_data.py`** to fabricate a vessel-call log with the same column layout and a similar order of magnitude, then runs it through the same fitting pipeline:

```
generate_synthetic_demo_data.py → data/raw/raw_data.xlsx
        ↓ build_processed_data.py
data/processed/berthing_log.csv
        ↓ fit_input_distributions.py  (fit-all: try several candidate distributions per
                                        variable, score by sum-of-squared-error against
                                        the empirical CDF, keep the winner + all candidates)
data/models/input_dist_record.csv   ← what distributions.py actually loads at import time
```

`input_dist_record.csv` is the only thing the running simulation reads — `raw_data.xlsx` and `berthing_log.csv` are training inputs to the fitting step, not consulted at runtime. Each row in the record carries the variable name, the winning distribution + parameters, the candidate distributions that were tried and their scores, and the sample size — so "this distribution was actually fitted, not hand-picked" is verifiable straight from the CSV.

| Variable | Fitted as | Notes |
|------|---------|------|
| Inter-arrival time | exponential | single fit across all calls |
| LPC (lifts per call), 7 groups | Beta within each group's range | groups with fewer than 30 samples fall back to Uniform — a conservative small-sample rule, not a bug |
| Crane count per group | deterministic (rounded group mean) | — |
| Idle time before / after service | lognormal | candidates: lognormal, gamma, exponential |
| Crane efficiency | normal | candidates: normal, gamma, lognormal |

### 3.2 Data generator

`generate_synthetic_demo_data.py` draws ~2,860 synthetic vessel calls (inter-arrival times, LPC by group, crane counts, idle times) from a set of demo-chosen parameters — deliberately different from any previously fitted real-data values, just plausible enough to exercise the same pipeline end to end. Disruption durations are sampled from `scenario_params.json`'s per-scenario min/max (no generator needed there — it's a small, explicitly declared config table).

---

## 4. Simulation configuration

| Parameter | Value | Rationale |
|------|---|------|
| Simulation type | Steady-state | the port runs continuously with no natural stopping point; 365 days is an observation window |
| Time unit | Hours | consistent with the fitted inter-arrival and idle-time distributions |
| Simulation length | 8,760 hrs (365 days) | annual loss estimation |
| Warm-up period | Estimated via Welch's (1983) method — n=200 replications, 7-day moving average, stabilizes within ±5% | implemented in `warmup_analysis.py`, re-run automatically whenever the port config changes |
| Berths | from `PortConfig.num_berths` (demo: 14) | |
| Quay cranes (normal) | from `PortConfig.num_quay_cranes` (demo: 72) | |
| Disruption model | Complete closure (Arena "Failure data"-equivalent) | cranes fully unavailable for the entire disruption+recovery window, then fully restored |

**Scenarios (25 disrupted + 1 intact):** `intact` has no disruption; `s01`–`s25` map Saffir-Simpson category 1–5 × distance bin 1–5 to a disruption-day range and damage-probability range from `scenario_params.json`. Each scenario injects one disruption at a uniformly random time within `[warm_up_hrs, sim_horizon_hrs - max_disruption_hrs]`, so the disruption never runs past the simulation boundary.

---

## 5. Replication plan

### 5.1 Seed design (common random numbers)

```python
base_seed = 42   # SimulationParams.random_seed_base
# scenario k, rep r → seed = base_seed + r
# stream separation: SeedSequence(base_seed + r).spawn(3)
#   → rng_arrival      drives inter-arrival sampling
#   → rng_ops          drives LPC / service-time sampling
#   → rng_disruption   drives disruption timing + duration
```

**CRN principle:** the same replication index uses the same RNG sub-streams across every scenario — every scenario "faces the same batch of ships." Disruption duration is mapped from each scenario's own Uniform(min, max) range using the same quantile draw (e.g. quantile 0.7 → a short duration for Cat 1, a long one for Cat 5), so scenarios differ in magnitude but not in which random branch was taken. This is what makes a paired t-test (§7) the right tool instead of an unpaired one — it removes between-scenario sampling noise that has nothing to do with the disruption itself.

### 5.2 Target precision

| Parameter | Value |
|------|---|
| Pilot size (n₀) | 10 |
| Target CI half-width | 5% of mean (matches `SimulationParams.target_ci_half_width = 0.05`) |
| Error margin | 0.05 |
| Formula | Kelton (2002): `h₀ = t_crit(df=n₀-1) × std / √n₀`; `n_required = ⌈n₀ × (h₀/h)²⌉` |
| Default replication count | 270 |

The replication count is driven by whichever scenario has the highest variance — in practice that's the most severe, longest-disruption scenario, because its outcome is bimodal: a short draw within that scenario's range lets the port catch up to near-intact throughput, while a long draw causes a large loss. That bimodality inflates the variance and pushes up the required sample size relative to the calmer scenarios, which is exactly the behavior Kelton's formula is meant to catch — a fixed replication count chosen up front would either under-sample the worst case or waste effort over-sampling the calm ones.

---

## 6. Verification & validation

### 6.1 VRF — programmatic face-validity checks

Run automatically on every E2 call (see `verification_validation.py::run_vrf_checks`):

1. Intact throughput falls within a plausible range for the configured port size.
2. Every disrupted scenario's throughput is ≤ intact (within a small floating-point tolerance — CRN can produce exact equality for 0-day disruptions).
3. Within the same distance bin, throughput decreases monotonically as typhoon category increases.
4. Within the same category, throughput increases monotonically as distance increases (farther = less impact).
5. The intact scenario's CI half-width is under 5% of its mean.
6. Every scenario serves a positive number of ship calls.

If any check fails, the pipeline returns a `FAILED_VALIDATION` status instead of proceeding — see `design_backend.md` §3 for what happens downstream.

### 6.2 VLD — sanity-check comparison against a benchmark reference

A common pattern for validating a port-operations simulation against reality: compare the intact-scenario output against a real operational record over some observation window, annualized to match the simulation's horizon, using a tolerance band rather than an exact match — since there's no independent paired observation to test against statistically, just "is the simulated output in a plausible neighborhood of the real one."

This demo follows the same mechanics with an **illustrative benchmark reference** calibrated for the demo, since the original confidential operational record can't be redistributed:

| KPI | 7-month reference | Annualized (×12/7) |
|-----|---------|------|
| Ship arrivals | 2,270 | ≈3,891 |
| Throughput (TEU) | 5,705,000 | ≈9,780,000 |

Tolerance: ±20%. The comparison computes `rel_error = (simulated - annualized_reference) / annualized_reference` per KPI and checks it's within tolerance — same code path, same pass/fail logic as a real validation would use; only the reference numbers are demo data rather than disclosed real operational figures.

---

## 7. Output analysis

Implemented in `output_analysis.py`, applied to all 25 disrupted scenarios vs. the intact baseline:

1. **Normality check** — Shapiro-Wilk on each scenario's per-replication throughputs. For n > 50 the test is sensitive to minor deviations, so failing it doesn't automatically force a different CI method — the central limit theorem covers it at this sample size; the result is recorded either way, not silently discarded.
2. **CI method selection** — if normal, a t-interval; otherwise picks between a t-interval (CLT, with a recorded warning), bootstrap, or log-transform based on sample size, skew, and the data's order-of-magnitude range.
3. **Paired comparison** (CRN-paired, so a paired t-test is valid): per scenario vs. intact — mean loss, relative loss %, paired t-statistic and p-value, and Cohen's dz as the effect size.
4. **Holm-Bonferroni correction** across all 25 comparisons, to control the family-wise error rate — running 25 hypothesis tests without correction would inflate the false-positive rate.
5. **Decision signal** — a three-way label per scenario: `DIFFERENT_AND_MEANINGFUL` (statistically significant *and* clears the practical threshold), `STAT_SIGNIFICANT_BUT_PRACTICALLY_NEGLIGIBLE` (significant but too small to act on), or `NOT_SIGNIFICANT`. This distinction is the point of §1.1's dual threshold: with enough replications, almost every scenario becomes statistically significant eventually, but only a few cause a throughput change large enough for a risk manager to actually act on.

A representative run (270 replications, intact throughput 9.156M TEU, 95% CI ±0.024M) flags **8 of 25 scenarios** as `DIFFERENT_AND_MEANINGFUL` — all of them Category 3 or higher at the closer distance bins (0–300 km). The calmer scenarios (low category, far distance, or both) land in `NOT_SIGNIFICANT` or the negligible-but-significant band: the port's queueing dynamics absorb a short disruption — ships that would have arrived during the closure simply queue and get served once it lifts, so utilization stays low enough to catch up within the year. Only long-enough closures, where the backlog can't be absorbed, clear the 5%-and-dz≥0.2 bar. The worst case (Category 5, 0–100 km) loses 35.55% of annual throughput. That pattern — most disruptions are absorbed, a structured minority aren't — is itself a useful sanity check on the model, not just an artifact of the statistics.

---

## 8. Implementation status

| Task | Area | File | Status |
|------|------|------|--------|
| T1 | Distributions | `simulation/distributions.py` | ✅ done — loads fitted parameters at import time, samples each variable |
| T2 | SimPy model | `simulation/simulation.py` | ✅ done — ship arrival process, disruption process, warm-up guard |
| T3 | Replication / CRN | `simulation/replication.py` | ✅ done — 3-stream seed separation, `run_single_replication`, `run_scenario` |
| T4 | Warm-up estimation | `simulation/warmup_analysis.py` | ✅ done — Welch's method |
| T5 | Verification / validation | `simulation/verification_validation.py` | ✅ done — VRF checks + VLD benchmark comparison |
| T6 | Output analysis | `simulation/output_analysis.py` | ✅ done — normality, CI selection, paired comparison, Holm correction |
| T7 | Report assembly | `simulation/report.py` | ✅ done — builds `SimulationResults`, the comparison table |
| T8 | Artifact persistence | `backend/artifacts.py` | ✅ done — every run writes a versioned folder under `outputs/` |
| T9 | Tests | `tests/` | ✅ 76 tests — distributions, CRN stream independence, replication-count formula, boundary cases |

**Known limitation, documented rather than hidden:** the disruption-strategy implementation (complete closure via mutating the SimPy `Resource`'s capacity) is a simplification appropriate for a demo; a production model would more likely use a dedicated failure-process abstraction with explicit interruption semantics for ships already mid-service. The current implementation doesn't interrupt in-service ships, which is noted in the comparison-table footnote generated by `report.py`.

---

## Amendment log

| Date | Change |
|------|--------|
| 2026-06-15 | Initial design: time units in hours; warm-up estimated via Welch's method; disruption modeled as complete closure; service time split into idle-before + service + idle-after. |
| 2026-06-15 | Warm-up re-estimated via Welch's method (n=200, 7-day window): stabilizes at day 5, replacing an earlier fixed estimate. |
| 2026-06-16 | Output analysis extended with Holm-Bonferroni correction and the three-way decision signal. |
| 2026-06-18 | Public version: real terminal data replaced with a synthetic, fitted vessel-call log; validation benchmark replaced with an illustrative reference; internal protocol references removed from this document. |

# Port Typhoon Risk Simulator — Backend Design

**Service:** `port_typhoon_simulator`
**Methodology source:** Cao & Lam (2018), *Reliability Engineering and System Safety* — simulation-based catastrophe-induced port loss estimation.
**Note on data:** this public version uses a synthetic vessel-call log and an illustrative demo port ("NPT") in place of the original confidential terminal dataset. The pipeline, schemas, and validation logic are unchanged — see `docs/design_simulation.md` §3 for how the synthetic data is generated and fitted.

---

## 1. Problem framing

**Problem:** given port configuration, historical typhoon track data, and disruption parameters, estimate per-scenario and total typhoon-induced port loss.

| Step | What it does |
|------|--------------|
| Parse typhoon track data → disruption scenario matrix | raw tracks → a 25-cell category × distance matrix |
| Simulate port operations → throughput decrease per scenario | configuration → throughput numbers |
| Compute losses (physical + economic) | throughput delta → USD loss |
| Aggregate historical / predicted totals | per-scenario losses → portfolio-level loss |

This is a pure data-transformation pipeline — there's no ranking of alternatives and no resource allocation under constraints. It turns raw hazard + operational data into structured loss estimates that a human risk manager uses to make mitigation decisions. That framing matters because it determines the rest of the design: no optimizer, no decision policy — just a deterministic chain of well-typed transformations, each independently testable and auditable.

---

## 2. Pipeline graph

```
IBTrACS file          Port config          Component values       Tariff data
     │                     │                     │                     │
     ▼                     ▼                     ▼                     ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│     E1       │    │     E2       │    │     E3       │    │     E4       │
│ load_typhoon │───▶│  run_simul-  │───▶│ estimate_    │───▶│ estimate_    │
│    _data     │    │   ation      │    │ physical_    │    │ economic_    │
│              │    │  ✅ SimPy DES │    │    loss      │    │    loss      │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
                                                │                     │
                                                ▼                     ▼
                                         ┌──────────────────────────────┐
                                         │             E5               │
                                         │       aggregate_losses        │
                                         │  (historical + predicted +   │
                                         │   worst-case per scenario)   │
                                         └──────────────────────────────┘
                                                         │
                                                         ▼
                                                ┌──────────────┐
                                                │     E6       │
                                                │ build_viz_   │
                                                │   payload    │
                                                └──────────────┘
                                                         │
                                                         ▼
                                                   [VizPayload]
                                                 (→ Streamlit/PyDeck)

─────────────────────────────────────────────────────────────────────────
Verification & audit layer (runs alongside the main pipeline, not inline)

Runtime integrity checks
    gate check at each step boundary — verifies completed-step order, output
    type, and throughput plausibility; runs async, never blocks the pipeline

Audit trail
    at pipeline end: a per-scenario table —
    scenario_id × [intact_teu, disrupted_teu, physical_loss, economic_loss, total_loss]
    — written out as a reviewable, versioned artifact
```

Each step is a plain function with a Pydantic-validated input and output (§5). E1 and E6 are sketched in the table below but not wired into the live pipeline yet — see the note after the table.

---

## 3. Pipeline table

| Step | Type | Purpose | Args | Returns | Side effects | Methodology | Error handling |
|------|------|---------|------|---------|--------------|-------------|----------------|
| E1 · `e1_load_typhoon_data` | Extract | Parse IBTrACS CSV; compute great-circle distance port↔typhoon center; classify each event into one of 25 scenarios (5 Saffir-Simpson categories × 5 distance bins, 0–500 km) | `ibtracs_path`, `port_lat`, `port_lon`, `radius_km=500.0`, `study_years` | `TyphoonTrackData` | — | Haversine distance + NOAA Saffir-Simpson thresholds | Hard fail if file missing or coords out of range; warn if <5 events found |
| E2 · `e2_run_simulation` | Execute | Run a SimPy discrete-event simulation of the terminal under the intact baseline and all 25 disrupted scenarios; return throughput (TEU) per scenario | `port_config`, `scenario_matrix`, `sim_params` | `SimulationResults` | Writes run artifacts (incl. verification/validation reports + comparison table) to `outputs/{timestamp}_{run_id}/e2_*` | SimPy DES (stochastic), replication-based (default n=270, Kelton 2002 sample-size formula) | Hard fail if `n_replications < 10` or intact throughput is 0; warn if CI half-width > 5% of mean |
| E3 · `e3_estimate_physical_loss` | Execute | Monte Carlo sampling of damage probability per scenario × component replacement cost; aggregate + per-equipment loss distribution | `scenario_matrix`, `port_components`, `n_mc_samples=10_000` | `PhysicalLossEstimates` | Writes `e3_output.json` + `e3_run_metadata.json` | Monte Carlo sampling; same damage-probability draw applied across components (internally consistent) | Hard fail if damage-probability bounds invalid |
| E4 · `e4_estimate_economic_loss` | Transform | `economic_loss = decreased_throughput × handling_charge_per_teu` per scenario | `sim_results`, `handling_charge_usd_per_teu` | `EconomicLossEstimates` | Writes `e4_output.json` + `e4_run_metadata.json` | Deterministic linear loss model | Hard fail if tariff ≤ 0 or any disrupted throughput exceeds intact (physically impossible) |
| E5 · `e5_aggregate_losses` | Transform | Sum physical + economic per scenario; compute historical total from scenario frequencies + study years; project a 5-year forward total | `physical`, `economic`, `scenario_matrix`, `port_config` | `LossProfile` | Writes `e5_output.json` + `e5_run_metadata.json` | Frequency-weighted aggregation | Hard fail if any scenario is missing from an input; warn if predicted > 10× historical/year |
| E6 · `e6_build_viz_payload` | Transform | Flatten track + loss data into PyDeck-ready GeoJSON for the map layers | `track_data`, `loss_profile`, `scenario_matrix` | `VizPayload` | — | Deterministic struct → GeoJSON mapping | Hard fail if `loss_profile` has fewer than 25 scenarios |

**Implementation status:** E2–E5 are implemented, tested, and wired into `pipeline.py`. E1 and E6 are designed but not built — `scenario_matrix` is currently loaded directly from the static `scenario_params.json` config instead of being derived from IBTrACS data, and the frontend reads pre-built track/preset JSON files (produced by the one-off `scripts/e1_parse_ibtracs.py` script) rather than calling a live `e1_load_typhoon_data` step. The risk-heatmap visualization that would consume E6's output was descoped from the frontend (see `design_frontend.md`).

**Persistence:** E2–E5 each accept `save_artifacts: bool = True` and `output_dir: Path | str | None = None`. Calling them standalone writes each into its own new `outputs/{timestamp}_{run_id}/` folder; `pipeline.py::run_full_pipeline()` computes one shared `output_dir` up front and threads it through E2→E3→E4→E5 so a full run lands in a single folder. It returns E2's own `FAILED_VALIDATION` dict early (skipping E3–E5) if the verification or validation checks fail.

**`run_single_scenario_pipeline(scenario_id)`** is the actual frontend entry point: it runs the simulation for the intact baseline plus one selected scenario only (full replication count × 2 runs instead of × 26, ~30 sec instead of several minutes), gets the per-equipment physical-loss breakdown for that one scenario, and reads historical totals from a pre-computed lookup (`scenario_loss_lookup.json`, built once by `scripts/build_scenario_loss_lookup.py` from a prior full run) instead of re-running E5. It returns a flat dict consumed directly by the frontend's view-model builder.

---

## 4. Verification & audit layer

| Check | Type | Purpose | Input | Output | Side effects | Error handling |
|-------|------|---------|-------|--------|--------------|-----------------|
| Runtime integrity check | Detect | After each step: verify step-completion order, check output type against the declared schema, flag implausible throughput | pipeline context | a check report | appended to a trace log | Non-blocking warning; only a severe anomaly raises |
| Audit trail | Transform | At pipeline end: produce a reviewable table of all 25 scenarios — `[scenario_id, cat, dist_bin, intact_teu, disrupted_teu, decreased_teu_pct, phys_loss_usd, econ_loss_usd, total_loss_usd, annual_freq]` | pipeline context | an audit table | written to a CSV file | Hard fail if a required field is missing |

This is separate from the statistical verification/validation done inside E2 itself (VRF face-validity checks + VLD sanity-check comparison against a benchmark reference — see `design_simulation.md` §6 for the methodology).

---

## 5. Data contracts (Pydantic models)

All step boundaries are validated Pydantic models — this is what makes the pipeline auditable: every input and output has an explicit, enforced shape, and a malformed value fails loudly at the boundary instead of propagating silently downstream. The full set lives in `src/backend/schemas.py`; the headline ones:

**`TyphoonTrackData`** (E1 output) — port identity + coordinates, study year range, list of `TyphoonEvent` (storm id, track points, strike distance, Saffir-Simpson category, distance bin, mapped scenario id).

**`ScenarioMatrix`** — exactly 25 `DisruptionScenario` entries (scenario id, category, distance bin, disruption-day range, damage-probability range) plus historical annual frequency per scenario.

**`PortConfig`** (E2 input) — port name, berth count, quay-crane count, baseline annual throughput, study period (this is the *historical IBTrACS record span* used by E5 for frequency-weighting, not the SimPy simulation horizon — that's set separately via `SimulationParams.sim_horizon_days`).

**`SimulationParams`** — `n_replications` (default 270), `sim_horizon_days` (default 365), `warm_up_days` (default 5, estimated by Welch's method — see `design_simulation.md` §4), `random_seed_base`, `target_ci_half_width`.

**`SimulationResults`** (E2 output) — one `SimRunResult` for the intact baseline plus exactly 25 for the disrupted scenarios. Each carries the mean throughput, CI half-width, the full vector of per-replication raw throughputs (kept specifically so the paired-comparison statistics in `design_simulation.md` §7 have something to operate on — discarding it down to just a mean would make that analysis impossible), and the normality test result + CI method actually used (recorded for audit, not just computed and thrown away).

**`PortComponents`** (E3 input) — quay cranes, gantry cranes, container trucks (each a count + unit replacement cost) plus a catch-all for other equipment.

**`PhysicalLossEstimates`** (E3 output) — per-scenario mean / std / p95 loss, plus the same broken down per equipment type. The four equipment components sum to the aggregate by construction (same Monte Carlo damage-probability draw applied to each).

**`EconomicLossEstimates`** (E4 output) — per-scenario decreased TEU (absolute + %) and the resulting USD loss.

**`LossProfile`** (E5 output) — full per-scenario breakdown plus historical total/annual-average, 5-year forward projection, and the worst-case scenario.

**`VizPayload`** (E6 output, not yet wired in) — typhoon tracks, risk heatmap points, and a 5×5 scenario grid, all as PyDeck-ready GeoJSON.

**`PipelineContext`** — the run-level container threading session id, timestamp, and every step's output through the pipeline, plus the verification report, completed-step list, and per-step error/timing log.

---

## 6. Software architecture

```
port_typhoon_simulator/
│
├── data/
│   ├── raw/raw_data.xlsx              ← synthetic vessel-call log (see design_simulation.md §3)
│   ├── processed/berthing_log.csv     ← cleaned, derived columns
│   ├── models/input_dist_record.csv   ← fitted distribution parameters (fit-all + SSE selection)
│   ├── typhoon_tracks/{sid}.json      ← per-storm track points (IBTrACS, public dataset)
│   └── typhoon_history.json           ← all qualifying historical events
│
├── docs/
│   ├── design_backend.md              ← this file
│   ├── design_simulation.md           ← DES design detail
│   └── design_frontend.md             ← frontend design
│
├── requirements.txt
├── pyproject.toml                     ← ruff + pytest config
│
├── scripts/
│   ├── generate_synthetic_demo_data.py
│   ├── build_processed_data.py
│   ├── fit_input_distributions.py
│   ├── e1_parse_ibtracs.py
│   └── build_scenario_loss_lookup.py
│
└── src/
    ├── app_streamlit.py                ← Streamlit + Plotly UI
    │
    ├── frontend/
    │   ├── state.py / state_schema.py  ← UI state machine
    │   └── view_models.py
    │
    └── backend/
        ├── schemas.py                  ← all Pydantic models (§5)
        ├── e_nodes.py                  ← E2–E5 (E1/E6 designed, not wired)
        ├── pipeline.py                 ← run_full_pipeline() / run_single_scenario_pipeline()
        ├── artifacts.py                ← run artifact persistence
        ├── simulation/                 ← SimPy model, distributions, replication, V&V, output analysis
        └── configs/
            ├── feature_flags.py
            ├── port_configs.json
            └── scenario_params.json

No external API calls at runtime. All data is local.
```

---

## 7. Sequence (single-scenario run, the actual frontend path)

```
User (Streamlit)     pipeline.py              e_nodes.py
     │                    │                       │
     │── click Run ──────►│                       │
     │                    │── e2 (intact + 1) ───►│── SimPy, n_replications reps each
     │                    │◄── SimulationResults ─│
     │                    │── e3 (1 scenario) ───►│── Monte Carlo, per-equipment breakdown
     │                    │◄── PhysicalLoss ──────│
     │                    │── e4 ────────────────►│── deterministic
     │                    │◄── EconomicLoss ──────│
     │                    │── read scenario_loss_lookup.json (historical, pre-computed)
     │◄── flat result dict ────────────────────────│
     │
     └── frontend builds ResultsViewModel → renders Streamlit tabs + map
```

For a full 26-scenario run (`run_full_pipeline()`), E2 is the bottleneck: `n_replications × 26 scenarios` SimPy runs. At the default 270 replications that's 7,020 runs, a few minutes serial.

---

## 8. Frontend chart inventory

Tracks which figures/tables from the original paper's methodology the frontend reproduces, and where each one's data comes from. Separate from `VizPayload` (§5), which only covers the map layers.

| Item | Description | Data source | Status |
|------|-------------|-------------|--------|
| Disruption/damage table | Disrupted/recovery period, frequency, damage probability % per scenario | `configs/scenario_params.json` (static input — stands in for E1's classifier output until E1 is built) | ✅ available |
| Comparison table | Decreased TEU / decreased % per category × distance bin | `e2_table9.txt`, `e2_comparison_table.csv` (E2 output) | ✅ done |
| Benchmark validation | Simulated vs. benchmark-reference comparison (ships, throughput) | `e2_vld_comparison.json` (E2's VLD check) | ✅ done |
| 3D vulnerability surface | Decreased TEU across category × distance, as a surface | Same data as the comparison table — frontend would pivot it into a 5×5 grid itself | data ready, no dedicated viz endpoint |
| Stacked loss bar chart | Physical + economic loss per distance bin, stacked by category | `e5_output.json` → `LossProfile.scenario_losses[]` | data ready, no dedicated viz endpoint |
| Year-by-year historical+predicted loss | Per-year actual + predicted total loss | **Out of scope.** E5 only produces aggregate totals over the study period, not a per-year series; a real yearly breakdown needs E1's per-year event counts plus an undefined year-splitting rule for the predicted side | won't implement |

---

## Amendment log

| Date | Change |
|------|--------|
| 2026-06-17 | E3 extended with per-equipment loss breakdown (quay crane / gantry crane / container truck / other equipment), mean + p95 each. |
| 2026-06-17 | Added `run_single_scenario_pipeline(scenario_id)` — the frontend's actual entry point, running intact + 1 scenario only; historical data from a pre-computed lookup. |
| 2026-06-17 | Frontend results view-model wired to the real pipeline. |
| 2026-06-17 | Risk heatmap marked out of scope for the frontend (E6 not built). |
| 2026-06-18 | Public version: real terminal data replaced with a synthetic vessel-call log; port identity genericized; internal protocol references removed from this document. |

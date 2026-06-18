# Port Typhoon Simulator — Frontend Design Doc

---

## 1. Product requirements

### Persona

**Port risk / operations manager** — a proficient web user, not a coder; familiar with typhoon-season emergency procedures and port operational KPIs.

**Decision context:** before or after a typhoon warning, needs a quick risk-exposure read, a loss forecast for management reporting, and support for emergency planning.

### Jobs to be done

1. When a typhoon warning is issued, estimate port downtime and loss magnitude to pre-position vessel schedules and emergency resources.
2. After typhoon season, review which historical typhoons struck the port and their individual loss magnitudes, to calibrate risk reserves.
3. When briefing management, export a report with loss figures to support emergency planning and insurance-pricing decisions.

### Platform

Web demo (no login) — Streamlit, desktop browser.

### User flow

```
1. Open app
   → Left panel: port parameters (demo terminal "NPT", fixed) + hazard-type tab (Typhoon selected)
   → Main area: empty map with prompt "Select a typhoon to begin"

2. Select a preset typhoon from the dropdown (name / year / category / strike distance)
   → Main area auto-plays the selected typhoon's IBTrACS track (animated dot, colored by Saffir-Simpson category)
   → Wind speed + time annotation updates each animation frame
   → Run button activates

3. [Optional] Toggle "Show Historical Typhoons" in the sidebar
   → Map overlays every historical track that struck the port

4. Click Run
   → Triggers the typhoon-impact simulation (~30 sec)
   → Step-by-step progress shown

5. Results page — typhoon info card (name / category badge / strike distance / disruption) above two tabs:
   Tab 1  Loss Summary       Throughput drop + physical loss (per-equipment) + economic / total loss
   Tab 2  Historical Records  Historical loss total + annual average + event list with individual loss estimates
   Below tabs: static typhoon-track + port snapshot map

6. Download report (Tab 1 or sidebar) → CSV or ZIP of the run's artifacts

7. Click New Analysis → return to step 1, clear results
```

### Persistence requirements

- File export required (CSV / ZIP), covering the E2–E5 run artifacts.
- No manual save, no versioned run history — this is a demo, not a production tool.

---

## 2. Feature list

| Module | Feature | Description | Priority |
|--------|---------|-------------|----------|
| Port info | Port parameter panel | Sidebar: demo terminal config (berths / quay cranes / design throughput / avg ship calls / coordinates), read-only | High |
| Port info | Hazard-type tab | Typhoon implemented; other hazards reserved (greyed out) | Med |
| Simulation control | Preset typhoon selector | Dropdown of historical typhoons (name / year / category / strike distance); selection maps to a scenario id | High |
| Simulation control | Run button | Triggers `run_single_scenario_pipeline(scenario_id)`: intact + selected scenario only (~30 sec) | High |
| Simulation control | Loading state | Step progress (simulation / physical & equipment loss / economic impact / report generation) + time estimate | High |
| Typhoon track | Dynamic path | Auto-plays the selected typhoon's IBTrACS track; animated dot colored by category; port location marked | High |
| Typhoon track | Animation annotation | Wind speed + timestamp, updated per animation frame | High |
| Typhoon track | Historical overlay | Checkbox to overlay all historical tracks that struck the port; default on | Med |
| Typhoon track | Distance annotation | Strike-distance ring on the map; distance also shown on the results info card | High |
| Loss summary | Throughput drop | Decreased TEU + decreased/intact % for the selected typhoon | High |
| Loss summary | Downtime & recovery | Disrupted + recovery period range (days), from the scenario config | High |
| Loss summary | Physical loss | Total mean + p95, and per-equipment breakdown | High |
| Loss summary | Economic loss | Economic loss USD + decreased TEU % | High |
| Loss summary | Total loss | Physical + economic, displayed prominently | High |
| Results | Typhoon info card | Name + category badge + strike distance + disruption label | High |
| Results | Track snapshot | Static map: full track + port marker + strike ring | Med |
| Historical records | Historical total loss | Aggregate total + annual average | High |
| Historical records | Typhoon event list | Per event: year / name / category / distance / loss estimate | High |
| Historical records | Model validation | Benchmark cross-check: simulated vs. reference (ships, TEU) | Low |
| Data export | CSV / ZIP | Comparison table + scenario-loss summary, or the full run output folder | Med |

---

## 3. Screens (wireframe)

> Platform: Streamlit (desktop browser). Global state machine: INIT → CONFIG → RUNNING → RESULTS. ERROR is a toast overlay, not a standalone screen.

### Screen A — CONFIG (empty)

```
┌──────────────────────────┬──────────────────────────────────────────────┐
│ NPT (demo terminal)      │                                              │
│ ─────────────────────    │                                              │
│ Port Parameters          │                                              │
│  Berths         : 14     │         ┌────────────────────────────┐       │
│  Quay Cranes    : 72     │         │                            │       │
│  Design Throughput       │         │   Select a typhoon         │       │
│    : 8.5M TEU/yr         │         │   to begin analysis        │       │
│  Avg Ship Calls : ~2,900 │         │                            │       │
│                          │         └────────────────────────────┘       │
│                          │                                              │
│ ── Hazard Type ──        │                                              │
│ [Typhoon ▪] [Fire] [EQ]  │                                              │
│                          │                                              │
│ ── Select Typhoon ──     │                                              │
│ ┌──────────────────────┐ │                                              │
│ │  -- Select typhoon ▼ │ │                                              │
│ └──────────────────────┘ │                                              │
│                          │                                              │
│ ┌──────────────────────┐ │                                              │
│ │    Run Simulation    │ │                                              │
│ │    ░░ disabled ░░    │ │                                              │
│ └──────────────────────┘ │                                              │
└──────────────────────────┴──────────────────────────────────────────────┘
```

### Screen B — CONFIG (typhoon selected)

```
┌──────────────────────────┬──────────────────────────────────────────────┐
│ NPT (demo terminal)      │                                              │
│  Berths:14  QC:72        │  ┌─────────────────────────────────────────┐ │
│  8.5M TEU/yr  ~2,900/yr  │  │   South China Sea (Scattergeo, 900px)   │ │
│                          │  │                                         │ │
│ ── Hazard Type ──        │  │   ⚓ NPT (pentagon marker)              │ │
│ [Typhoon ▪] [Fire] [EQ]  │  │    \  track line colored by Cat        │ │
│                          │  │     ●●●●●  dots = 6-hourly, Cat color  │ │
│ ── Select Typhoon ──     │  │     •  animated head dot (track_color)  │ │
│ ┌──────────────────────┐ │  │   ⊙ strike-distance ring (dashed orange)│ │
│ │ Vicente 2012  Cat4 ▼ │ │  │                                         │ │
│ └──────────────────────┘ │  │   [▶ Play]  [⏸ Pause]   2012-07-24 00 │ │
│                          │  │                         Vmax: 115 kt ◀ann│ │
│ ☑ Show Historical        │  └─────────────────────────────────────────┘ │
│   Typhoons (1994–2026)   │                                              │
│                          │                                              │
│ ── Estimate Loss ──      │                                              │
│  Predict physical loss   │                                              │
│  and economic loss for   │                                              │
│  this attack.            │                                              │
│                          │                                              │
│ ┌──────────────────────┐ │                                              │
│ │  ▶  Run Simulation   │ │                                              │
│ └──────────────────────┘ │                                              │
└──────────────────────────┴──────────────────────────────────────────────┘
```

Note: historical tracks load from a local JSON file (E1's cached output) and are shown by default — no simulation required. The checkbox toggles them on/off.

### Screen C — RUNNING (~30 sec)

```
┌──────────────────────────┬──────────────────────────────────────────────┐
│ ░░ NPT ░░                │                                              │
│ ░░ (all disabled) ░░     │          ⟳  Running simulation…             │
│                          │                                              │
│ ░░ Hazard Type ░░        │   ┌──────────────────────────────────────┐   │
│ ░░░░░░░░░░░░░░░          │   │ ⟳  Port Operations Simulation        │   │
│                          │   │ ○  Physical & Equipment Loss         │   │
│ ░░ Select Typhoon ░░     │   │ ○  Economic Impact Analysis          │   │
│ ░░░░░░░░░░░░░░░░░        │   │ ○  Report Generation                 │   │
│                          │   └──────────────────────────────────────┘   │
│ ░░ Run (disabled) ░░     │                                              │
│                          │          Estimated time: ~30 seconds         │
│                          │                                              │
│                          │  ── ERROR TOAST (on failure only) ────────   │
│                          │  ┌────────────────────────────────────────┐  │
│                          │  │ ✖  Simulation failed: FAILED_VALIDATION│  │
│                          │  │    <status message>          [Retry]   │  │
│                          │  └────────────────────────────────────────┘  │
└──────────────────────────┴──────────────────────────────────────────────┘
```
Legend: ✔ green/complete · ⟳ spinning/active · ○ grey/waiting

### Screen D — RESULTS · Tab 1 Loss Summary

```
┌──────────────────────────┬──────────────────────────────────────────────┐
│ NPT (demo terminal)      │ ┌─── Typhoon Info Card ───────────────────┐  │
│  Berths:14  QC:72        │ │ Vicente 2012  [Cat 4]  ◉ 130 km  ⏱ 50–190d│
│                          │ └────────────────────────────────────────────┘│
│ Vicente 2012  Cat4       │                                              │
│ ─────────────────────    │ [📊 Loss Summary ▪] [🕰 Historical Records]  │
│ [↓ Download CSV]         │ ─────────────────────────────────────────    │
│ [↓ Download ZIP]         │                                              │
│                          │  Throughput Impact · Vicente 2012            │
│ [New Analysis]           │  ┌─────────────────┐  ┌─────────────────┐   │
│                          │  │ Decreased TEU   │  │  vs. Intact (%) │   │
│                          │  │   1,850  TEU    │  │    − 28.4 %     │   │
│                          │  └─────────────────┘  └─────────────────┘   │
│                          │                                              │
│                          │  Physical Loss Breakdown                     │
│                          │  ┌────────────────────────────────────────┐  │
│                          │  │ Equipment        Mean         p95      │  │
│                          │  │ Quay Crane     $X.X M USD  $X.X M USD │  │
│                          │  │ Gantry Crane   $X.X M USD  $X.X M USD │  │
│                          │  │ Container Truck$X.X M USD  $X.X M USD │  │
│                          │  │ Other Equipment$X.X M USD  $X.X M USD │  │
│                          │  │ ─────────────────────────────────────  │  │
│                          │  │ Total Physical $X.X M USD  $X.X M USD │  │
│                          │  └────────────────────────────────────────┘  │
│                          │                                              │
│                          │  ┌──────────────┐ ┌──────────────┐          │
│                          │  │Economic Loss │ │  Total Loss  │          │
│                          │  │  $X.X M USD  │ │  $XX.X M USD │          │
│                          │  └──────────────┘ └──────────────┘          │
│                          │                                              │
│                          │  ────────────────────────────────────────    │
│                          │  Typhoon Track · Vicente 2012                │
│                          │  ┌────────────────────────────────────────┐  │
│                          │  │  [static Scattergeo 300px: full track  │  │
│                          │  │   + category-colored dots + port marker│  │
│                          │  │   + strike ring + 🌀 at origin]        │  │
│                          │  └────────────────────────────────────────┘  │
└──────────────────────────┴──────────────────────────────────────────────┘
```

### Screen E — RESULTS · Tab 2 Historical Records

```
┌──────────────────────────┬──────────────────────────────────────────────┐
│ NPT (demo terminal)      │ ┌─── Typhoon Info Card ───────────────────┐  │
│  Berths:14  QC:72        │ │ Vicente 2012  [Cat 4]  ◉ 130 km  ⏱ 50–190d│
│                          │ └────────────────────────────────────────────┘│
│ Vicente 2012  Cat4       │                                              │
│ ─────────────────────    │ [📊 Loss Summary] [🕰 Historical Records ▪]  │
│ [↓ Download CSV]         │ ─────────────────────────────────────────    │
│ [↓ Download ZIP]         │                                              │
│                          │  ┌───────────────────────────────────────┐   │
│ [New Analysis]           │  │ Historical Total Loss  (1994–2026)    │   │
│                          │  │   $X,XXX M USD                        │   │
│                          │  │   Annual avg: $XX.X M USD             │   │
│                          │  │   Based on historical IBTrACS events  │   │
│                          │  └───────────────────────────────────────┘   │
│                          │                                              │
│                          │  Typhoon Strike History (NPT, 1994–2026)    │
│                          │  ┌─────────────────────────────────────────┐ │
│                          │  │ Year  Name       Cat  Dist    Est. Loss │ │
│                          │  │ 2023  Saola       4   62 km  $309.6 M  │ │
│                          │  │ 2018  Mangkhut    2  137 km   $49.4 M  │ │
│                          │  │ 2017  Hato        3   93 km  $167.7 M  │ │
│                          │  │ 2012  Vicente     4  130 km  $110.0 M  │ │
│                          │  │  ...  ...        ... ...      ...      │ │
│                          │  └─────────────────────────────────────────┘ │
│                          │  Validation (benchmark reference):           │
│                          │  Ships: Reality X / Sim X                   │
│                          │  TEU:   Reality X / Sim X                   │
│                          │                                              │
│                          │  ────────────────────────────────────────    │
│                          │  Typhoon Track · Vicente 2012                │
│                          │  ┌────────────────────────────────────────┐  │
│                          │  │  [static Scattergeo 300px: full track  │  │
│                          │  │   + category-colored dots + port marker│  │
│                          │  │   + strike ring + 🌀 at origin]        │  │
│                          │  └────────────────────────────────────────┘  │
└──────────────────────────┴──────────────────────────────────────────────┘
```

Typhoon names/years/categories above (Vicente, Mangkhut, Hato, Saola, …) are real historical storms from the public IBTrACS record — not the confidential port's data.

### Streamlit component map

| Area | Function | Streamlit API |
|------|----------|---------------|
| Step progress (RUNNING) | 4-step status indicator | `st.status()` |
| Typhoon track map | IBTrACS path animation; dots colored by Saffir-Simpson category; animated head dot | `st.plotly_chart()` (Plotly Scattergeo, `go.Frame` animation) |
| Animation annotation | Wind speed + timestamp overlay (bottom-right, per-frame) | Plotly `layout.annotations` updated per `go.Frame` |
| Results typhoon info card | Name / category badge / strike dist / disruption — above tabs | `st.markdown()` (inline HTML card) |
| Results tab bar | 2 result tabs | `st.tabs()` |
| Metric cards | Decreased TEU / EL / TL | `st.metric()` |
| Equipment loss table | Physical loss per-equipment breakdown | `st.dataframe()` |
| Historical records table | Typhoon strike history | `st.dataframe()` |
| Track snapshot | Static Scattergeo (300 px) — track + port + strike ring, below tabs | `st.plotly_chart()` (Plotly Scattergeo, no animation) |
| Download buttons | CSV / ZIP | `st.download_button()` |
| Error toast | Simulation failure | `st.error()` |
| Sidebar | Port info + hazard type + typhoon selector + historical checkbox + Estimate Loss section + Run | `st.sidebar.*` |

---

## 4. Screen → backend action map

| Screen | User action | Backend call | State change | Expected UI |
|--------|-------------|--------------|--------------|-------------|
| CONFIG | Page load | `load_typhoon_presets()` (local JSON) | INIT → CONFIG | Port panel; typhoon dropdown populated; empty-map prompt |
| CONFIG | Select preset typhoon | `load_typhoon_track(typhoon_id)` (local JSON) | typhoon selection updated | Info card shown; track auto-plays; Run activates |
| CONFIG | Toggle historical overlay | none | toggle flips | Historical-track layer added/removed (pre-loaded) |
| CONFIG | Click Run | `run_single_scenario_pipeline(scenario_id)` | CONFIG → RUNNING | Step progress panel |
| RUNNING | Simulation succeeds | none | RUNNING → RESULTS | Switch to results; Tab 1 active |
| RUNNING | Simulation fails | none | RUNNING → CONFIG (error) | Error toast + retry; selection retained |
| RESULTS | Switch tab | none | active tab updated | Tab 1 ↔ Tab 2 |
| RESULTS | Download CSV / ZIP | `export_csv` / `export_zip` | — | Browser download |
| RESULTS | New Analysis | none | RESULTS → CONFIG | Clear results, keep port parameters |
| ERROR | Retry | `run_single_scenario_pipeline(scenario_id)` | ERROR → RUNNING | Re-trigger |

---

## 5. UI state machine

**States:**
- **INIT** — app starts, loads presets; no interaction until loaded.
- **CONFIG** — idle state; Run disabled until a typhoon is selected.
- **RUNNING** — simulation in progress (~30 sec); controls disabled, step progress shown.
- **RESULTS** — two result tabs visible; export and New Analysis available.
- **ERROR** — simulation failed; error banner + retry; selection retained.

```
              presets_loaded
  [start] ──────────────────▶ CONFIG ──────────────────────────────────┐
                                 │  run_clicked                         │
                                 │  (guard: a typhoon is selected)      │
                                 ▼                                      │
                             RUNNING                                    │ new_analysis_clicked
                            /       \                                   │
              sim_completed /         \ sim_failed                      │
                           ▼           ▼                                │
                       RESULTS       ERROR ──── retry_clicked ──▶ RUNNING
                           │
                           └──────────────────────────────────────────▶┘
```

This is implemented as a pure state-transition function (`src/frontend/state.py`) — given `(current_state, event, guard_data)`, it returns the next state and a patch to apply to session state. It never writes `st.session_state` directly, which is what makes it unit-testable without spinning up Streamlit.

---

## 6. Session state contract

```python
# src/frontend/state_schema.py
class AppState(BaseModel):
    stage: Literal["INIT", "CONFIG", "RUNNING", "RESULTS", "ERROR"] = "INIT"

    selected_typhoon_id: Optional[str] = None
    selected_scenario_id: Optional[int] = None
    show_history_tracks: bool = True

    active_tab: Literal["loss_summary", "historical_records"] = "loss_summary"
    output_dir: Optional[str] = None
    results_vm: Optional[dict] = None

    error_msg: Optional[str] = None
```

---

## 7. Frontend pipeline graph

| Step | Type | Input | Output | Notes |
|------|------|-------|--------|-------|
| Load presets | Extract | `configs/typhoon_presets.json` | `dict[str, PresetEntry]` | Called once on INIT, cached |
| Load track | Extract | `data/typhoon_tracks/{sid}.json` | `list[TrackPoint]` | Called on selection, cached by id |
| Load all tracks | Extract | every file in `data/typhoon_tracks/` | `list[list[TrackPoint]]` | For the historical overlay, cached once |
| State transition | Select | `(current_state, event, guard_data)` | next state + patch | Pure function; never touches session state directly |
| Build results view-model | Transform | pipeline result + typhoon info | `ResultsViewModel` | Only place that touches the raw pipeline result's nested fields |
| Run | Execute | `scenario_id` | pipeline result dict | Side effect: calls `run_single_scenario_pipeline()`, ~30 sec |
| Export CSV / ZIP | Execute | `output_dir` | bytes | Side effect: reads from disk, triggers browser download |
| Render (config / running / results) | Generate | state + data | Streamlit widgets | Pure render, no side effects |

Rule: anything that writes to disk, calls the pipeline, or mutates persistent state lives in an "execute" function — never inside a render function. Render functions are pure: state in, widgets out.

---

## 8. View-model contracts

```python
class TyphoonInfoViewModel(BaseModel):
    typhoon_id: str
    display_name: str
    category: int
    strike_dist_km: float
    disruption_label: str

class EquipmentLossRow(BaseModel):
    label: str
    mean_usd: float
    p95_usd: float

class HistoricalTyphoonRow(BaseModel):
    year: int
    name: str
    category: int
    dist_km: float
    loss_usd: float

class ResultsViewModel(BaseModel):
    typhoon_display_name: str
    decreased_teu: float
    decreased_teu_pct: float
    equipment_rows: list[EquipmentLossRow]
    physical_loss_total_mean_usd: float
    physical_loss_total_p95_usd: float
    economic_loss_usd: float
    total_loss_usd: float
    historical_total_usd: float
    historical_annual_avg_usd: float
    historical_typhoons: list[HistoricalTyphoonRow]
    output_dir: str
```

A `PTS_MOCK=1` environment flag skips the real ~30-second pipeline call and loads a fixture `ResultsViewModel` instead — purely for fast UI iteration during development; production always runs the real pipeline.

---

## 9. Render contract

| Component | Input | Output | Side effects |
|---|---|---|---|
| `_render_config` | state, presets, track data | sidebar + map | — |
| `_render_running` | state | step progress panel | — |
| `_render_results_tab1` | `ResultsViewModel` | metrics + equipment table | — |
| `_render_results_tab2` | `ResultsViewModel` | historical metrics + table + validation panel | — |
| `_render_error_banner` | error message | error box + retry button | — |
| `_run_pipeline` (execute) | `scenario_id` | pipeline result dict | calls the pipeline, ~30 sec |
| `_export_csv` / `_export_zip` (execute) | `output_dir` | bytes | reads from disk |

---

## 10. Error handling

| Source | Severity | UI response |
|---|---|---|
| Pipeline returns a failure status | Hard | → ERROR state; error message + retry |
| Pipeline raises an uncaught exception | Hard | → ERROR state; generic error + retry |
| Pipeline timeout | Hard | → ERROR state; timeout message |
| Presets file missing | Hard | Block at INIT; explicit error, no further UI |
| A single track file missing | Soft | Skip animation; port-only map; Run still enabled |
| Some historical track files missing | Soft | Load what's available; warning shown |
| Results view-model build fails | Hard | → ERROR state |
| Export fails | Warn | Stay in RESULTS; warning shown |
| Unrecognised (state, event) pair | Hard | Raised as an exception, surfaced as a generic error |

---

## 11. Test scenario list

| Area | Scenario | Input | Expected |
|---|---|---|---|
| State | INIT → CONFIG | `presets_loaded` | next state CONFIG |
| State | select valid typhoon | `typhoon_selected(sid)` | selection + scenario id set |
| State | run with typhoon selected | `run_clicked` | next state RUNNING |
| State | run without selection | `run_clicked`, no selection | guard fails, stays CONFIG |
| State | run completes | `sim_completed(...)` | next state RESULTS, view-model populated |
| State | run fails | `sim_failed(msg)` | next state ERROR, message set |
| State | retry | `retry_clicked` | next state RUNNING |
| State | new analysis | `new_analysis_clicked` | next state CONFIG, results cleared |
| State | unknown event | unrecognised `(state, event)` | raises an error |
| View-model | normal build | mock pipeline result | every field populated; total = physical + economic |
| View-model | equipment row order | mock result | exactly 4 rows, fixed order |
| View-model | historical sort | events out of order | sorted by year descending |
| Export | CSV from view-model | mock `ResultsViewModel` | CSV bytes match the on-screen summary, not all 25 scenarios |
| Export | ZIP from view-model | mock `ResultsViewModel` | ZIP contains exactly the scenario summary + historical records |

---

## 12. Implementation status

| Task | Area | File | Status |
|------|------|------|--------|
| T1 | UI state machine | `frontend/state.py` | ✅ done |
| T2 | Session state contract | `frontend/state_schema.py` | ✅ done |
| T3 | View-model builders | `frontend/view_models.py` | ✅ done |
| T4 | CONFIG / RUNNING / RESULTS render + error banner | `app_streamlit.py` | ✅ done |
| T5 | Typhoon track animation + historical overlay | `app_streamlit.py` (Plotly Scattergeo) | ✅ done |
| T6 | Data export (CSV / ZIP) | `app_streamlit.py` | ✅ done — exports only the run shown on screen |
| T7 | Risk heatmap / 5×5 scenario grid (PyDeck) | — | ⬜ descoped — never built; E6 only produces track + port-marker data (see `design_backend.md` §9) |

**Known limitation, documented rather than hidden:** there are no automated tests for the Streamlit render functions or the state machine itself — `tests/` covers the backend pipeline (E-nodes, simulation internals) and the view-model transforms, but `state.py`'s transition table and the render functions are currently verified by manual testing only.

---

## Amendment log

| Date | Change |
|------|--------|
| 2026-06-17 | Frontend wired to the real pipeline via `run_single_scenario_pipeline()`. |
| 2026-06-18 | Public version: port identity genericized; internal protocol references removed from this document. |
| 2026-06-18 | Restored the screen wireframes (Screens A–E) that were cut from the first public draft for length. Download buttons fixed to export only the on-screen run, not a 25-scenario lookup table. |

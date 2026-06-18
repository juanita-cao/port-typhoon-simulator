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

## 3. Screen → backend action map

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

## 4. UI state machine

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

## 5. Session state contract

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

## 6. Frontend pipeline graph

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

## 7. View-model contracts

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

## 8. Render contract

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

## 9. Error handling

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

## 10. Test scenario list

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
| Export | valid output dir | mock run folder | CSV / ZIP bytes returned, parseable |

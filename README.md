# Port Typhoon Risk Simulator

A simulation-driven decision-support tool that estimates typhoon-induced container-port losses: given a port configuration and a typhoon's category and strike distance, it runs a discrete-event simulation of port operations under disruption, then turns the resulting throughput loss into physical and economic loss estimates with a statistical audit trail behind every number.

Methodology follows Cao & Lam (2018), *Reliability Engineering and System Safety*. **The data is synthetic** — see [Data note](#data-note) below.

---

## What this demonstrates

- **A pipeline, not a black box.** Every step (load typhoon data → simulate → estimate physical loss → estimate economic loss → aggregate) has an explicit Pydantic schema at its input and output. A malformed value fails loudly at the boundary instead of propagating silently three steps downstream.
- **Statistical rigor over a single number.** Replication count isn't a guess — it's derived from a pilot study via Kelton's (2002) formula. Scenarios are compared using common random numbers (CRN) so a paired t-test is valid, corrected for multiple comparisons (Holm-Bonferroni), with an effect size (Cohen's dz) alongside the p-value — because "statistically significant" and "operationally worth acting on" are different questions, and the model answers both.
- **Verification before trust.** Every run is checked against face-validity rules (does throughput actually decrease as the typhoon gets closer and stronger?) before its output is allowed downstream, plus a sanity-check comparison against a benchmark reference — both fully automated, both producing an artifact a reviewer can open and check by hand.
- **Reproducible artifacts.** Every run writes a timestamped folder with the full comparison table, the verification/validation reports, and a human-readable summary — not just whatever happened to print to the console.
- **Design before code.** The three documents in [`docs/`](docs/) were written before the corresponding implementation: problem framing and pipeline shape first, then the simulation's statistical design, then the frontend's state machine — in that order, each reviewed before the next was built on top of it.

---

## Architecture

```
IBTrACS data ──► load typhoon data ──► run simulation ──► physical loss ──┐
                                            (SimPy DES)         (Monte Carlo)  │
                                                                              ▼
                                                                    economic loss ──► aggregate losses
                                                                                              │
                                                                                              ▼
                                                                                      Streamlit + map UI
```

Full pipeline table, data contracts, and sequence diagrams: [`docs/design_backend.md`](docs/design_backend.md).
Simulation design (entity model, distribution fitting, replication plan, verification/validation): [`docs/design_simulation.md`](docs/design_simulation.md).
Frontend design (state machine, view models, screen flow): [`docs/design_frontend.md`](docs/design_frontend.md).

---

## Quickstart

```bash
pip install -r requirements.txt

# run the test suite (76 tests: distributions, CRN stream independence,
# replication-count formula, schema validation)
pytest tests/ -v

# lint
ruff check .

# launch the UI
streamlit run src/app_streamlit.py

# or run the full 26-scenario pipeline from the command line
python -c "from backend.pipeline import run_full_pipeline; run_full_pipeline(verbose=True)"
```

Requires Python 3.11+ (uses `X | Y` union type syntax evaluated at runtime by Pydantic).

CI runs the same lint + test commands on every push — see [`.github/workflows/test.yml`](.github/workflows/test.yml).

---

## Data note

The original version of this project used a real container terminal's confidential 2016 vessel-call log. That dataset isn't redistributable, so this public version generates a **synthetic vessel-call log** (`scripts/generate_synthetic_demo_data.py`) with the same column structure and a similar order of magnitude, then runs it through the same distribution-fitting pipeline (`build_processed_data.py` → `fit_input_distributions.py`) that the original used. The port itself ("NPT") and its berth/crane counts are illustrative, not a real terminal's specs. The validation benchmark in `verification_validation.py` is likewise an illustrative reference value, calibrated to exercise the same pass/fail logic a real validation would use.

Everything else — the pipeline architecture, the schemas, the statistical methodology, the test suite — is unchanged from the original.

The typhoon track data (IBTrACS) is a real, public meteorological dataset and is used as-is.

---

## Project structure

```
data/             synthetic vessel-call log, fitted distributions, public IBTrACS typhoon tracks
docs/             design documents (read before the corresponding code was written)
scripts/          one-off data generation / fitting / preprocessing scripts
src/backend/      pipeline steps, schemas, SimPy simulation, statistics, artifact persistence
src/frontend/     Streamlit state machine and view models
src/app_streamlit.py   the UI entry point
tests/            76 tests covering distributions, replication, output analysis
```

---

## Status

Implemented and tested: the simulation step, physical/economic loss estimation, loss aggregation, the full statistical verification/validation layer, and the Streamlit frontend's single-scenario flow.

Designed but not built: parsing typhoon tracks into the scenario matrix live (currently a static config file stands in for it) and the PyDeck risk-heatmap visualization that would consume it. Both are documented in `docs/design_backend.md` along with everything else still open.

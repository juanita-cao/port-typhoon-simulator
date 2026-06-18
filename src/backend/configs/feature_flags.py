"""
Runtime feature flags. All switches in one place.
Default values must be production-safe (real path, not mock).
"""
import os

# ── Simulation Pipeline ─────────────────────────────────────────────────────
USE_MOCK_PIPELINE: bool = os.getenv("PTS_MOCK", "0") == "1"
# True  → skip run_single_scenario_pipeline(); return _MOCK_RESULTS_VM fixture.
#         Dev/demo only. Launch: PTS_MOCK=1 streamlit run src/app_streamlit.py
# False → call real pipeline (~30 sec). Production default.

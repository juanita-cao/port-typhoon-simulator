"""Session state contract for Port Typhoon Simulator (Artifact 2).

All keys used in st.session_state are defined here.
App init: ``st.session_state.update(AppState().model_dump())``
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class AppState(BaseModel):
    """Complete schema for st.session_state. All keys present at app init."""

    stage: Literal["INIT", "CONFIG", "RUNNING", "RESULTS", "ERROR"] = "INIT"

    # Typhoon selection (CONFIG onwards)
    selected_typhoon_id: str | None = None
    selected_scenario_id: int | None = None
    show_history_tracks: bool = True

    # Results (RESULTS state)
    active_tab: Literal["loss_summary", "historical_records"] = "loss_summary"
    output_dir: str | None = None
    results_vm: dict | None = None

    # Error (ERROR state)
    error_msg: str | None = None

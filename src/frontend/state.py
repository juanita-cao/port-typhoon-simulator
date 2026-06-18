"""UI state node — pure state transition function.

Never writes st.session_state directly.
App layer calls _apply_patch(result.session_state_patch) then st.rerun().
"""
from __future__ import annotations

from typing import Any, NamedTuple


class StateTransitionResult(NamedTuple):
    next_state: str
    session_state_patch: dict[str, Any]


def f_state(current_state: str, event: str, **kwargs: Any) -> StateTransitionResult:
    """Map (current_state, event, guard_data) → StateTransitionResult.

    Raises ValueError for any unrecognised (state, event) pair so that
    missing transitions fail loudly (Artifact 8: HARD fail on unknown pair).
    """
    match (current_state, event):

        # ── INIT ──────────────────────────────────────────────────────────
        case ("INIT", "presets_loaded"):
            return StateTransitionResult("CONFIG", {"stage": "CONFIG"})

        # ── CONFIG / ERROR — typhoon selected ─────────────────────────────
        case ("CONFIG" | "ERROR", "typhoon_selected"):
            sid: str | None = kwargs.get("sid")
            sid_valid: bool = bool(kwargs.get("sid_is_valid", False))
            if sid and sid_valid:
                return StateTransitionResult(
                    current_state,
                    {
                        "selected_typhoon_id": sid,
                        "selected_scenario_id": kwargs.get("scenario_id"),
                    },
                )
            # Guard fail: sid not in presets or None — no change
            return StateTransitionResult(current_state, {})

        # ── CONFIG / ERROR — history overlay toggled ───────────────────────
        case ("CONFIG" | "ERROR", "history_toggled"):
            current_val: bool = bool(kwargs.get("show_history_tracks", True))
            return StateTransitionResult(current_state, {"show_history_tracks": not current_val})

        # ── CONFIG / ERROR — run / retry clicked ──────────────────────────
        case ("CONFIG" | "ERROR", "run_clicked"):
            if kwargs.get("selected_typhoon_id") is not None:
                return StateTransitionResult(
                    "RUNNING",
                    {"stage": "RUNNING", "error_msg": None},
                )
            # Guard fail: Run button should be disabled; no state change
            return StateTransitionResult(current_state, {})

        # ── ERROR — dedicated retry button ────────────────────────────────
        case ("ERROR", "retry_clicked"):
            if kwargs.get("selected_typhoon_id") is not None:
                return StateTransitionResult(
                    "RUNNING",
                    {"stage": "RUNNING", "error_msg": None},
                )
            return StateTransitionResult("ERROR", {})

        # ── RUNNING — simulation completed ────────────────────────────────
        case ("RUNNING", "sim_completed"):
            return StateTransitionResult(
                "RESULTS",
                {
                    "stage": "RESULTS",
                    "output_dir": kwargs.get("output_dir_str", ""),
                    "results_vm": kwargs.get("results_vm_dict"),
                    "error_msg": None,
                },
            )

        # ── RUNNING — simulation failed ───────────────────────────────────
        case ("RUNNING", "sim_failed"):
            return StateTransitionResult(
                "ERROR",
                {
                    "stage": "ERROR",
                    "error_msg": kwargs.get("msg", "Simulation failed"),
                },
            )

        # ── RESULTS — tab switch ──────────────────────────────────────────
        case ("RESULTS", "tab_switched"):
            tab: str = kwargs.get("tab", "loss_summary")
            if tab in {"loss_summary", "historical_records"}:
                return StateTransitionResult("RESULTS", {"active_tab": tab})
            return StateTransitionResult("RESULTS", {})

        # ── RESULTS — downloads (side effect handled in eXecute helper) ───
        case ("RESULTS", "download_csv_clicked" | "download_zip_clicked"):
            return StateTransitionResult("RESULTS", {})

        # ── RESULTS — new analysis ────────────────────────────────────────
        case ("RESULTS", "new_analysis_clicked"):
            return StateTransitionResult(
                "CONFIG",
                {
                    "stage": "CONFIG",
                    "output_dir": None,
                    "results_vm": None,
                    "error_msg": None,
                },
            )

        # ── Catch-all: HARD fail ──────────────────────────────────────────
        case _:
            raise ValueError(
                f"Unrecognised (state={current_state!r}, event={event!r})"
            )

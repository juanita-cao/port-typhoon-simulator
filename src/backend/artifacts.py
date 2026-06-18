"""Output artifact persistence.

Three artifact categories persisted after each E-node completes:
  Run Metadata     → JSON  (run_id / timestamp / protocol_version / design_doc_hash)
  Pipeline Edge    → JSON  (Pydantic schema for downstream E-nodes / pipeline restart)
  V&V              → CSV   (comparison table + statistical-comparison stats for audit)
  Human Audit      → TXT   (Table 9 matrix for stakeholder review)

Default output path: {service_root}/outputs/{timestamp}_{run_id_short}/
One folder per run — never overwritten. Pass output_dir explicitly to override.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from backend.schemas import (
    EconomicLossEstimates,
    LossProfile,
    PhysicalLossEstimates,
    SimulationResults,
)
from backend.simulation.report import build_comparison_table, format_table9
from backend.simulation.verification_validation import (
    run_vld_comparison,
    run_vrf_checks,
    vrf_summary,
)

_SERVICE_ROOT = Path(__file__).parent.parent.parent
_OUTPUTS_ROOT = _SERVICE_ROOT / "outputs"
_DESIGN_DOC_PATH = _SERVICE_ROOT / "docs" / "design_simulation.md"


def _default_output_dir(run_metadata: dict) -> Path:
    """outputs/{timestamp}_{run_id_short}/ — one folder per run, run_id suffix avoids same-second collisions."""
    ts = datetime.fromisoformat(run_metadata["timestamp"]).strftime("%Y%m%d_%H%M%S")
    return _OUTPUTS_ROOT / f"{ts}_{run_metadata['run_id'][:8]}"

PROTOCOL_VERSION = "v2"

_COMPARISON_COLS = [
    "scenario_id", "typhoon_cat", "dist_bin", "dist_range_km",
    "decreased_teu", "decreased_pct",
    "normality_p_value", "is_normal", "ci_method",
    "t_statistic", "mean_loss_teu", "ci_half_width_loss_teu",
    "dz", "p_value",
    "is_significant_raw", "is_significant_holm", "is_significant",
    "correction_method", "operationally_meaningful", "decision_signal",
]


def build_run_metadata(
    n_replications: int | None = None,
    random_seed_base: int | None = None,
    protocol_version: str = PROTOCOL_VERSION,
    design_doc_path: Path | None = None,
    **extra,
) -> dict:
    """Build run-level traceability metadata.

    design_doc_hash lets you detect parameter changes between runs:
    if the hash differs, the design doc changed since the last run.
    n_replications/random_seed_base are E2-specific and optional so this same
    builder serves E3-E5 (pass node-specific fields via **extra, e.g. n_mc_samples=).
    """
    doc_path = design_doc_path or _DESIGN_DOC_PATH
    try:
        doc_hash = hashlib.sha256(doc_path.read_bytes()).hexdigest()[:8]
    except FileNotFoundError:
        doc_hash = "n/a"

    meta = {
        "run_id":            str(uuid.uuid4()),
        "timestamp":         datetime.now(UTC).isoformat(),
        "protocol_version":  protocol_version,
        "design_doc_hash":   doc_hash,
    }
    if n_replications is not None:
        meta["n_replications"] = n_replications
    if random_seed_base is not None:
        meta["random_seed_base"] = random_seed_base
    meta.update(extra)
    return meta


def save_e2_artifacts(
    results: SimulationResults,
    run_metadata: dict,
    output_dir: Path | str | None = None,
    warmup_result: dict | None = None,
) -> tuple[Path, dict, dict]:
    """Persist E2 artifacts. Returns the directory written to.

    Files written:
        e2_run_metadata.json     Traceability — run_id / timestamp / protocol_version / design_doc_hash
        e2_output.json           Pipeline edge — full SimulationResults for E4/pipeline
        e2_warmup_analysis.json  V&V          — Welch warm-up analysis result (steady-state detection)
        e2_comparison_table.csv  V&V          — 25-row comparison table + statistical-comparison stats
        e2_s44_stats.csv         V&V          — statistical decision columns + run metadata injected
        e2_vrf_report.json       V&V          — VRF (Verification — face-validity check) results
        e2_vld_comparison.json   V&V          — VLD (Validation — sanity check vs benchmark reference)
        e2_table9.txt            Human        — Table 9-style 5×5 matrix
    """
    out = Path(output_dir) if output_dir is not None else _default_output_dir(run_metadata)
    out.mkdir(parents=True, exist_ok=True)

    # Run Metadata
    (out / "e2_run_metadata.json").write_text(
        json.dumps(run_metadata, indent=2, ensure_ascii=False)
    )

    # Pipeline edge artifact
    (out / "e2_output.json").write_text(results.model_dump_json(indent=2))

    # V&V Artifact — Welch warm-up analysis (steady-state detection)
    if warmup_result is not None:
        warmup_payload = {
            "run_id":    run_metadata["run_id"],
            "timestamp": run_metadata["timestamp"],
            "protocol":  "Welch (1983) daily moving-average",
            "result":    warmup_result,
        }
        (out / "e2_warmup_analysis.json").write_text(
            json.dumps(warmup_payload, indent=2, ensure_ascii=False)
        )

    # V&V Artifacts — statistical comparison table
    comp = build_comparison_table(results, include_paired_stats=True)
    comp.to_csv(out / "e2_comparison_table.csv", index=False)

    # s44_stats: inject run metadata as first columns so each CSV is self-describing
    s44_df = comp[[c for c in _COMPARISON_COLS if c in comp.columns]].copy()
    s44_df.insert(0, "run_id",           run_metadata["run_id"])
    s44_df.insert(1, "timestamp",        run_metadata["timestamp"])
    s44_df.insert(2, "protocol_version", run_metadata["protocol_version"])
    s44_df.insert(3, "design_doc_hash",  run_metadata["design_doc_hash"])
    s44_df.to_csv(out / "e2_s44_stats.csv", index=False)

    # V&V Artifacts — VRF (Verification — programmatic face-validity checks)
    vrf_checks = run_vrf_checks(results)
    vrf_report = {
        "run_id":    run_metadata["run_id"],
        "timestamp": run_metadata["timestamp"],
        "summary":   vrf_summary(vrf_checks),
        "checks":    vrf_checks,
    }
    (out / "e2_vrf_report.json").write_text(
        json.dumps(vrf_report, indent=2, ensure_ascii=False)
    )

    # V&V Artifacts — VLD (Validation — sanity check vs benchmark reference)
    # tolerance_pct declared in design_simulation.md, VLD section
    vld_result = run_vld_comparison(results, tolerance_pct=0.20)
    vld_result["run_id"] = run_metadata["run_id"]
    vld_result["timestamp"] = run_metadata["timestamp"]
    (out / "e2_vld_comparison.json").write_text(
        json.dumps(vld_result, indent=2, ensure_ascii=False)
    )

    # Human Audit Artifact
    (out / "e2_table9.txt").write_text(format_table9(comp))

    return out, vrf_report, vld_result


def save_e3_artifacts(
    estimates: PhysicalLossEstimates,
    run_metadata: dict,
    output_dir: Path | str | None = None,
) -> Path:
    """Persist E3 artifacts. Returns the directory written to.

    Files written:
        e3_run_metadata.json   Traceability  — run_id / timestamp / protocol_version / design_doc_hash
        e3_output.json         Pipeline edge — full PhysicalLossEstimates for E5/pipeline
    """
    out = Path(output_dir) if output_dir is not None else _default_output_dir(run_metadata)
    out.mkdir(parents=True, exist_ok=True)
    (out / "e3_run_metadata.json").write_text(
        json.dumps(run_metadata, indent=2, ensure_ascii=False)
    )
    (out / "e3_output.json").write_text(estimates.model_dump_json(indent=2))
    return out


def save_e4_artifacts(
    estimates: EconomicLossEstimates,
    run_metadata: dict,
    output_dir: Path | str | None = None,
) -> Path:
    """Persist E4 artifacts. Returns the directory written to.

    Files written:
        e4_run_metadata.json   Traceability  — run_id / timestamp / protocol_version / design_doc_hash
        e4_output.json         Pipeline edge — full EconomicLossEstimates for E5/pipeline
    """
    out = Path(output_dir) if output_dir is not None else _default_output_dir(run_metadata)
    out.mkdir(parents=True, exist_ok=True)
    (out / "e4_run_metadata.json").write_text(
        json.dumps(run_metadata, indent=2, ensure_ascii=False)
    )
    (out / "e4_output.json").write_text(estimates.model_dump_json(indent=2))
    return out


def save_e5_artifacts(
    profile: LossProfile,
    run_metadata: dict,
    output_dir: Path | str | None = None,
) -> Path:
    """Persist E5 artifacts. Returns the directory written to.

    Files written:
        e5_run_metadata.json   Traceability  — run_id / timestamp / protocol_version / design_doc_hash
        e5_output.json         Pipeline edge — full LossProfile for E6/frontend
    """
    out = Path(output_dir) if output_dir is not None else _default_output_dir(run_metadata)
    out.mkdir(parents=True, exist_ok=True)
    (out / "e5_run_metadata.json").write_text(
        json.dumps(run_metadata, indent=2, ensure_ascii=False)
    )
    (out / "e5_output.json").write_text(profile.model_dump_json(indent=2))
    return out

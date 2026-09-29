"""Read-only resource layer for SignalScope AI (v2.6).

Transport-independent: every resource takes simple Python arguments, calls
the existing engines, and returns plain JSON-safe dicts, lists and scalars.
A future HTTP transport only parses the URL, calls one of these functions
and serialises the result. No resource writes a file, changes audit
state, calls Gemini or reads the Gemini key; all business rules stay in
audit_config, audit_history, run_structured_batch_audit, the report and
findings engines, measurement_engine and run_monitoring_cycle.

Expected failures raise ReadonlyApiError(status, code, message); anything
else is a programming error for the transport to report as a 500.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from audit_config import AuditConfig, AuditConfigError, _check_slug, load_audit_config, validate_audit_config_data
from audit_history import (
    CONFIG_FILENAME,
    QUESTIONS_FILENAME,
    RESULTS_FILENAME,
    SNAPSHOTS_DIRNAME,
    STATE_RESET_INTERRUPTED,
    AuditHistoryError,
    NotComparableError,
    SnapshotInfo,
    SnapshotIntegrityError,
    _audits_root,
    active_run_state,
    compute_snapshot_comparison,
    inspect_active_run,
    inspect_snapshot,
    list_snapshots,
    parse_run_id,
)
from audit_runner import load_questions
from geo_findings_analyzer import ALL_BUYER_JOURNEY_STAGES, compute_findings
from measurement_engine import _maturity_tier, _positive_sentiment_rate, _source_coverage_rate, _stage_coverage_count
from report_generator import (
    _parse_semicolon_list,
    compute_brand_visibility,
    compute_engine_coverage,
    compute_mention_frequency,
    compute_sentiment_summary,
    compute_stage_coverage,
)
from run_monitoring_cycle import (
    OUTCOME_ALREADY_RUNNING,
    MonitoringError,
    lock_path,
    plan_cycle,
    probe_lock,
    validate_interval_days,
)
from run_structured_batch_audit import STATE_EVIDENCE_INTEGRITY_ERROR, STATE_LABELS
from version import SIGNALSCOPE_VERSION
from write_single_audit_result import load_existing_results

READONLY_API_CONTRACT_VERSION = 1

@dataclass(frozen=True)
class ReadonlyApiError(Exception):
    """An expected failure of a read-only resource, with the HTTP-style
    status a transport should use. Carries no stack trace or internals."""

    status: int
    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.status} {self.code}: {self.message}"


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def _slug(slug: object) -> str:
    """The released audit_config slug rule, and nothing stricter."""
    try:
        _check_slug(slug)
    except AuditConfigError as exc:
        raise ReadonlyApiError(400, "invalid_slug", str(exc)) from None
    return slug  # type: ignore[return-value]


def _run_id(run_id: object) -> str:
    try:
        parse_run_id(run_id)
    except AuditHistoryError as exc:
        raise ReadonlyApiError(400, "invalid_run_id", str(exc)) from None
    return run_id  # type: ignore[return-value]


def _interval(interval_days: object) -> int:
    try:
        return validate_interval_days(interval_days)
    except MonitoringError as exc:
        raise ReadonlyApiError(400, "invalid_interval", str(exc)) from None


def _audit_dir(slug: str, audits_dir) -> Path:
    folder = _audits_root(audits_dir) / slug
    if not folder.is_dir():
        raise ReadonlyApiError(404, "unknown_audit", f"Unknown audit {slug!r}.")
    return folder


def _config(slug: str, audits_dir) -> AuditConfig:
    _audit_dir(slug, audits_dir)
    try:
        return load_audit_config(slug, audits_dir=_audits_root(audits_dir))
    except AuditConfigError as exc:
        raise ReadonlyApiError(404, "not_found", str(exc)) from None


# --------------------------------------------------------------------------
# Shared serialisers (explicit contract fields only)
# --------------------------------------------------------------------------


def _percent(part: int, whole: int) -> float | None:
    return part / whole * 100 if whole else None


def _current_run_summary(slug: str, audits_dir) -> dict:
    summary = {
        "readable": False, "error": None, "state": None, "detail": None, "question_count": None,
        "structurally_complete_count": None, "coverage_percent": None, "result_row_count": None,
        "evidence_problem_count": None, "requested_models": None,
    }
    try:
        active = inspect_active_run(slug, audits_dir=audits_dir)
        state = active_run_state(slug, audits_dir=audits_dir)
    except AuditHistoryError as exc:
        summary["error"] = str(exc)
        return summary
    complete = active.structurally_complete_count
    summary.update({
        "readable": True,
        "state": state.state,
        "detail": state.detail,
        "question_count": active.question_count,
        "structurally_complete_count": complete,
        "coverage_percent": _percent(complete, active.question_count),
        "result_row_count": active.result_row_count,
        "evidence_problem_count": sum(1 for s in active.states if s.state == STATE_EVIDENCE_INTEGRITY_ERROR),
        "requested_models": list(active.requested_models),
    })
    return summary


def _snapshot_summary(info: SnapshotInfo) -> dict:
    manifest = info.manifest if isinstance(info.manifest, dict) else {}

    def field(name, kind):
        value = manifest.get(name)
        return value if isinstance(value, kind) and not isinstance(value, bool) else None

    models = manifest.get("requested_models")
    return {
        "run_id": info.run_id,
        "valid": info.is_valid,
        "problems": [str(p) for p in info.problems],
        "created_at": field("created_at", str),
        "status": field("status", str),
        "signalscope_version": field("signalscope_version", str),
        "question_count": field("question_count", int),
        "structurally_complete_count": field("structurally_complete_count", int),
        "requested_models": [m for m in models if isinstance(m, str)] if isinstance(models, list) else None,
    }


def _latest_snapshot(snapshots: list[SnapshotInfo]) -> dict | None:
    return _snapshot_summary(snapshots[-1]) if snapshots else None


def _row_basis(rows: list[dict[str, str]]) -> dict:
    return {
        "total_rows": len(rows),
        "rows_by_engine": dict(sorted(compute_engine_coverage(rows).items())),
        "unique_questions": len({r["question_id"] for r in rows if r.get("question_id")}),
    }


def _dataset_metrics(rows: list[dict[str, str]], question_count: int) -> dict | None:
    """All-row KPIs of one dataset (a current run or one snapshot), from the
    existing report and measurement helpers. None for an empty dataset."""
    if not rows:
        return None
    visibility = compute_brand_visibility(rows)
    sentiment = compute_sentiment_summary(rows)
    stage_counts = compute_stage_coverage(rows)
    rows_per_stage = {stage: stage_counts.get(stage, 0) for stage in ALL_BUYER_JOURNEY_STAGES}
    rows_per_stage.update({stage: count for stage, count in sorted(stage_counts.items())
                           if stage not in rows_per_stage})
    return {
        "brand_visibility": {
            "rate_percent": visibility["rate"],
            "cited": visibility["y"],
            "not_cited": visibility["n"],
            "considered": visibility["considered"],
            "excluded": visibility["excluded"],
        },
        "brand_mention_frequency": visibility["y"],
        "positive_sentiment": {
            "rate_percent": _positive_sentiment_rate(rows),
            "positive": sentiment["positive"],
            "neutral": sentiment["neutral"],
            "negative": sentiment["negative"],
            "excluded": sentiment["excluded"],
        },
        "authority_sources": {
            "distinct_count": len(compute_mention_frequency(rows, "sources_cited")),
            "rows_with_sources_percent": _source_coverage_rate(rows),
        },
        "funnel_stage_coverage": {
            "stages_covered": _stage_coverage_count(rows),
            "stages_total": len(ALL_BUYER_JOURNEY_STAGES),
            "rows_per_stage": rows_per_stage,
        },
        "geo_maturity": {"tier": _maturity_tier(rows, question_count)},
    }


def _findings(rows: list[dict[str, str]], question_count: int, config: AuditConfig) -> list[dict]:
    if not rows:
        return []
    return [
        {"title": f.title, "value": f.value, "evidence": f.evidence, "confidence": f.confidence}
        for f in compute_findings(rows, question_count, audit_config=config)
    ]


def _gemini_result(row: dict[str, str] | None) -> dict | None:
    if row is None:
        return None
    position = (row.get("brand_position") or "").strip()
    return {
        "run_date": row.get("run_date") or None,
        "brand_cited": row.get("brand_cited") or None,
        "brand_position": int(position) if position.isdigit() else None,
        "competitors_cited": _parse_semicolon_list(row.get("competitors_cited")),
        "sources_cited": _parse_semicolon_list(row.get("sources_cited")),
        "sentiment": row.get("sentiment") or None,
        "answer_snippet": row.get("answer_snippet") or None,
    }


def _audit_listing(slug: str, audits_dir) -> tuple[AuditConfig, dict, list[SnapshotInfo]]:
    config = _config(slug, audits_dir)
    return config, _current_run_summary(slug, audits_dir), list_snapshots(slug, audits_dir=audits_dir)


# --------------------------------------------------------------------------
# Resources
# --------------------------------------------------------------------------


def get_health() -> dict:
    return {
        "status": "ok",
        "signalscope_version": SIGNALSCOPE_VERSION,
        "contract_version": READONLY_API_CONTRACT_VERSION,
        "read_only": True,
    }


def get_audits(*, audits_dir: str | Path | None = None) -> dict:
    """Every audit folder: loadable audits with their current run and
    latest snapshot, and folders that could not be loaded (never hidden)."""
    root = _audits_root(audits_dir)
    audits, invalid = [], []
    folders = sorted(p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")) \
        if root.is_dir() else []
    for folder in folders:
        try:
            config = load_audit_config(folder, audits_dir=root)
        except AuditConfigError as exc:
            invalid.append({"folder": folder, "error": str(exc)})
            continue
        snapshots = list_snapshots(config.slug, audits_dir=root)
        audits.append({
            "slug": config.slug,
            "brand": config.brand,
            "company_name": config.company_name,
            "market": config.market,
            "category": config.category,
            "competitors": list(config.competitors),
            "current_run": _current_run_summary(config.slug, root),
            "latest_snapshot": _latest_snapshot(snapshots),
            "snapshot_count": len(snapshots),
        })
    return {"audits": audits, "invalid_audits": invalid}


def get_audit(slug: str, *, audits_dir: str | Path | None = None) -> dict:
    slug = _slug(slug)
    config, current, snapshots = _audit_listing(slug, audits_dir)
    return {
        "slug": config.slug,
        "brand": config.brand,
        "company_name": config.company_name,
        "report_subject": config.report_subject,
        "market": config.market,
        "category": config.category,
        "competitors": list(config.competitors),
        "question_library": config.question_library,
        "current_run": current,
        "latest_snapshot": _latest_snapshot(snapshots),
    }


def get_current_run(slug: str, *, audits_dir: str | Path | None = None) -> dict:
    """The current run: summary, all-row metrics and findings, and every
    question in question-library order with its state and structured
    Gemini result (never raw evidence)."""
    slug = _slug(slug)
    config = _config(slug, audits_dir)
    current = _current_run_summary(slug, audits_dir)
    result = {"slug": slug, "current_run": current, "row_basis": None, "metrics": None, "findings": [],
              "questions": []}
    if not current["readable"]:
        return result
    active = inspect_active_run(slug, audits_dir=audits_dir)
    rows = load_existing_results(str(active.audit_dir / RESULTS_FILENAME))
    result["row_basis"] = _row_basis(rows)
    if current["state"] != STATE_RESET_INTERRUPTED:
        result["metrics"] = _dataset_metrics(rows, active.question_count)
        result["findings"] = _findings(rows, active.question_count, config)
    by_id = {q["question_id"]: q for q in active.questions}
    result["questions"] = [
        {
            "question_id": state.question_id,
            "buyer_journey_stage": by_id[state.question_id]["buyer_journey_stage"],
            "question": by_id[state.question_id]["question"],
            "state_code": state.state,
            "state_label": STATE_LABELS[state.state],
            "detail": state.detail,
            "gemini_result": _gemini_result(state.row),
        }
        for state in active.states
    ]
    return result


def _snapshot_dataset(info: SnapshotInfo, slug: str) -> tuple[AuditConfig, list[dict[str, str]], int]:
    """A valid snapshot's own config, result rows and question count."""
    data = json.loads((info.path / CONFIG_FILENAME).read_text(encoding="utf-8-sig"))
    config = validate_audit_config_data(data, source=str(info.path / CONFIG_FILENAME))
    questions = load_questions(str(info.path / QUESTIONS_FILENAME))
    rows = load_existing_results(str(info.path / RESULTS_FILENAME))
    return config, rows, len(questions)


def get_snapshots(slug: str, *, audits_dir: str | Path | None = None) -> dict:
    """Every snapshot in run-ID order, with its own all-row metrics when
    valid (the raw material for trends); no findings, no fallback."""
    slug = _slug(slug)
    _config(slug, audits_dir)
    entries = []
    for info in list_snapshots(slug, audits_dir=audits_dir):
        entry = _snapshot_summary(info)
        metrics = None
        if info.is_valid:
            _, rows, question_count = _snapshot_dataset(info, slug)
            metrics = _dataset_metrics(rows, question_count)
        entries.append({**entry, "metrics": metrics})
    return {"slug": slug, "snapshots": entries}


def get_snapshot(slug: str, run_id: str, *, audits_dir: str | Path | None = None) -> dict:
    slug = _slug(slug)
    run_id = _run_id(run_id)
    folder = _audit_dir(slug, audits_dir) / SNAPSHOTS_DIRNAME / run_id
    if not folder.is_dir():
        raise ReadonlyApiError(404, "unknown_snapshot", f"No snapshot {run_id} for audit {slug}.")
    info = inspect_snapshot(folder, slug=slug)
    snapshots = list_snapshots(slug, audits_dir=audits_dir)
    result = {"slug": slug, "snapshot": _snapshot_summary(info),
              "is_latest": bool(snapshots) and snapshots[-1].run_id == run_id,
              "row_basis": None, "metrics": None, "findings": []}
    if info.is_valid:
        config, rows, question_count = _snapshot_dataset(info, slug)
        result["row_basis"] = _row_basis(rows)
        result["metrics"] = _dataset_metrics(rows, question_count)
        result["findings"] = _findings(rows, question_count, config)
    return result


def get_comparison(
    slug: str,
    from_run: str,
    to_run: str,
    *,
    audits_dir: str | Path | None = None,
    generated_at: date | None = None,
) -> dict:
    """compute_snapshot_comparison (never compare_snapshots, which writes a
    report). A methodology mismatch is a normal comparable=false result."""
    slug = _slug(slug)
    from_run, to_run = _run_id(from_run), _run_id(to_run)
    snapshots_dir = _audit_dir(slug, audits_dir) / SNAPSHOTS_DIRNAME
    for run_id in (from_run, to_run):
        if not (snapshots_dir / run_id).is_dir():
            raise ReadonlyApiError(404, "unknown_snapshot", f"No snapshot {run_id} for audit {slug}.")
    try:
        comparison = compute_snapshot_comparison(slug, from_run, to_run, audits_dir=audits_dir,
                                                 generated_at=generated_at)
    except NotComparableError as exc:
        return {"slug": slug, "from_run": from_run, "to_run": to_run, "comparable": False,
                "problems": [str(p) for p in exc.problems]}
    except SnapshotIntegrityError as exc:
        raise ReadonlyApiError(409, "snapshot_invalid", str(exc)) from None
    except AuditHistoryError as exc:
        raise ReadonlyApiError(400, "comparison_refused", str(exc)) from None
    context, progress = comparison.context, comparison.progress
    return {
        "slug": slug,
        "from_run": from_run,
        "to_run": to_run,
        "comparable": True,
        "from": {"structurally_complete_count": context.from_complete, "question_count": context.from_total},
        "to": {"structurally_complete_count": context.to_complete, "question_count": context.to_total},
        "unequal_coverage": (context.from_complete, context.from_total) != (context.to_complete, context.to_total),
        "shared_question_count": comparison.shared_question_count,
        "shared_question_ids": list(comparison.shared_question_ids),
        "warnings": {
            "requested_models": comparison.requested_model_warning,
            "signalscope_version": comparison.version_warning,
        },
        "metrics": [
            {"metric_name": m.metric_name, "before": m.before, "after": m.after, "difference": m.difference,
             "direction": m.direction}
            for m in progress.metrics
        ],
        "overall_assessment": progress.overall_assessment,
        "generated_at": progress.generated_at.isoformat(),
    }


def get_monitoring_plan(
    slug: str,
    interval_days: int,
    *,
    audits_dir: str | Path | None = None,
    now: Callable[[], datetime] | None = None,
) -> dict:
    """The monitoring planner's view, like the CLI dry run but without any
    API-key check: collection plans assume credentials are configured,
    and api_key_check says the check was not performed."""
    slug = _slug(slug)
    interval_days = _interval(interval_days)
    _audit_dir(slug, audits_dir)
    # Slug and interval are validated above; a lock that cannot be probed
    # (MonitoringLockError) is an operational failure, not a client error.
    plan = plan_cycle(slug, interval_days, audits_dir=audits_dir, now=now, api_key_present=lambda: True)
    lock_held = probe_lock(lock_path(slug, audits_dir=audits_dir))
    return {
        "slug": slug,
        "interval_days": interval_days,
        "plan_outcome": plan.outcome,
        "outcome": OUTCOME_ALREADY_RUNNING if lock_held else plan.outcome,
        "planned_steps": list(plan.steps),
        "active_state": plan.active_state,
        "latest_snapshot": plan.latest_snapshot,
        "previous_snapshot": plan.previous_snapshot,
        "due": plan.due,
        "requires_collection": plan.requires_collection,
        "integrity_problems": plan.integrity_problems,
        "methodology_differences": list(plan.methodology_differences),
        "reasons": list(plan.reasons),
        "api_key_check": "not_performed",
        "lock_held": lock_held,
    }

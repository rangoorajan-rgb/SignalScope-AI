"""Audit run history for SignalScope AI (v2.4).

Preserves an audit's current run as an immutable snapshot:

    audits/<slug>/snapshots/<run-id>/
        snapshot_manifest.json
        audit_config.json  buyer_questions.csv  audit_results.csv
        raw_responses/<question_id>__gemini.json   (if the run has evidence)
        reports/audit_report.md  reports/GEO_FINDINGS.md

The source files are copied byte for byte, so a snapshot stays
interpretable even if the audit's config or questions change later. The
two reports are rendered from the snapshot's own copies (no Gemini call).
The manifest records provenance, coverage and a SHA-256 hash of every
other file, and every read verifies those hashes.

A snapshot is built in a staging folder inside snapshots/, checked, and
published with a single rename, so either the complete snapshot exists or
nothing does. The current run is only ever read. Nothing ever writes into
a published snapshot.

After a verified snapshot, "new-run" clears the run-specific current
files so a fresh run can be collected: raw_responses/ is first moved into
a hidden retirement folder inside snapshots/, audit_results.csv is reset
to its header, and the retired evidence (verified against the snapshot)
is deleted. The config and questions are kept. An interrupted new-run is
recognised and finished by running new-run again; at every step the
verified snapshot holds the complete previous run.

"compare" measures change between two snapshots of the same audit, read
only from the snapshots' own validated copies. The runs must share the
same core configuration and question library; only Gemini questions
structurally complete in both runs are measured, with the existing
measurement engine. The derived report is written to
reports/<slug>/comparisons/<from-run>__<to-run>/GEO_PROGRESS.md.

    python src/audit_history.py snapshot --audit <slug> [--allow-partial]
    python src/audit_history.py new-run --audit <slug>
    python src/audit_history.py compare --audit <slug> --from-run <run-id> --to-run <run-id>
    python src/audit_history.py list --audit <slug>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

import audit_config
from audit_config import (
    CONFIG_FILENAME,
    AuditConfig,
    AuditConfigError,
    _check_slug,
    load_audit_config,
    validate_audit_config_data,
)
from audit_runner import AuditRunnerError, load_questions
from geo_findings_analyzer import generate_geo_findings
from measurement_engine import MeasurementEngineError, Progress, RunComparisonContext, compare_audits, render_markdown
from report_generator import ReportGeneratorError, generate_report
from run_structured_batch_audit import (
    EVIDENCE_DIRNAME,
    STATE_EVIDENCE_INTEGRITY_ERROR,
    QuestionProcessingError,
    QuestionState,
    EvidenceIntegrityError,
    _duplicate_gemini_rows,
    classify_question,
    is_structurally_complete,
    load_evidence,
    validate_question_ids,
)
from version import SIGNALSCOPE_VERSION
from write_single_audit_result import WriteAuditResultError, load_existing_results, write_results_atomically

SNAPSHOTS_DIRNAME = "snapshots"
MANIFEST_FILENAME = "snapshot_manifest.json"
QUESTIONS_FILENAME = "buyer_questions.csv"
RESULTS_FILENAME = "audit_results.csv"
REPORTS_DIRNAME = "reports"
AUDIT_REPORT_PATH = f"{REPORTS_DIRNAME}/audit_report.md"
FINDINGS_REPORT_PATH = f"{REPORTS_DIRNAME}/GEO_FINDINGS.md"
SOURCE_FILES = (CONFIG_FILENAME, QUESTIONS_FILENAME, RESULTS_FILENAME)
REQUIRED_SNAPSHOT_FILES = (*SOURCE_FILES, AUDIT_REPORT_PATH, FINDINGS_REPORT_PATH)

# Staging and retirement folders start with "." so they can never be taken
# for a snapshot. Retirement folders live inside snapshots/ (git-ignored).
STAGING_PREFIX = ".creating-"
RETIRED_PREFIX = ".retired-raw-"
_RETIRED_NAME_PATTERN = re.compile(r"\.retired-raw-(\d{8}T\d{6}Z)-[0-9a-f]+")

# Derived states of the current run (see active_run_state).
STATE_FRESH = "fresh"
STATE_IN_PROGRESS = "in progress / partial"
STATE_COMPLETE = "complete"
STATE_SNAPSHOTTED = "snapshotted"
STATE_RESET_INTERRUPTED = "reset interrupted"

MANIFEST_FORMAT_VERSION = 1
MANIFEST_FIELDS = (
    "format_version",
    "audit_slug",
    "run_id",
    "created_at",
    "signalscope_version",
    "status",
    "question_count",
    "structurally_complete_count",
    "requested_models",
    "files",
)
STATUS_COMPLETE = "complete"
STATUS_PARTIAL = "partial"

RUN_ID_FORMAT = "%Y%m%dT%H%M%SZ"
CREATED_AT_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_RUN_ID_PATTERN = re.compile(r"\d{8}T\d{6}Z")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class AuditHistoryError(Exception):
    """An audit history operation cannot be carried out."""


class SnapshotIntegrityError(AuditHistoryError):
    """A snapshot, or the run being snapshotted, fails an integrity check."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# Run IDs
# --------------------------------------------------------------------------


def run_id_for(moment: datetime) -> str:
    """The run ID for a timezone-aware moment: its UTC time as
    YYYYMMDDTHHMMSSZ (sortable, safe as a Windows folder name)."""
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise AuditHistoryError("Snapshot times must be timezone-aware.")
    return moment.astimezone(timezone.utc).strftime(RUN_ID_FORMAT)


def created_at_for(run_id: str) -> str:
    """The manifest created_at value for a run ID (the same instant in
    ISO-8601 UTC)."""
    return parse_run_id(run_id).strftime(CREATED_AT_FORMAT)


def parse_run_id(run_id: object) -> datetime:
    """Validate a run ID strictly and return its UTC moment."""
    if not isinstance(run_id, str) or not _RUN_ID_PATTERN.fullmatch(run_id):
        raise AuditHistoryError(f"Invalid run ID {run_id!r}: expected YYYYMMDDTHHMMSSZ.")
    try:
        return datetime.strptime(run_id, RUN_ID_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise AuditHistoryError(f"Invalid run ID {run_id!r}: not a real UTC time.") from exc


# --------------------------------------------------------------------------
# Hashes
# --------------------------------------------------------------------------


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_safe_relative_path(path: object) -> bool:
    if not isinstance(path, str) or not path or "\\" in path or path.startswith("/"):
        return False
    parts = path.split("/")
    return all(part and part not in (".", "..") and ":" not in part for part in parts)


def snapshot_artifact_paths(root: Path) -> list[str]:
    """Every file under a snapshot root except the manifest, as sorted
    POSIX paths relative to the root."""
    return sorted(
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and not (p.parent == root and p.name == MANIFEST_FILENAME)
    )


def build_hash_map(root: Path, relative_paths: list[str]) -> dict[str, str]:
    return {path: hash_file(root / path) for path in sorted(relative_paths)}


def verify_hash_map(root: Path, files: object) -> list[str]:
    """Problems with a declared {relative path: sha256} map for root:
    unsafe paths, invalid digests, missing files, modified bytes, and
    files present but not declared."""
    if not isinstance(files, dict) or not files:
        return ["files must be a non-empty mapping of relative paths to SHA-256 digests"]
    problems: list[str] = []
    for path, digest in files.items():
        if not _is_safe_relative_path(path):
            problems.append(f"unsafe file path {path!r}")
            continue
        if path == MANIFEST_FILENAME:
            problems.append("the manifest must not hash itself")
            continue
        if not isinstance(digest, str) or not _SHA256_PATTERN.fullmatch(digest):
            problems.append(f"invalid SHA-256 digest for {path}")
            continue
        target = root / path
        if not target.is_file():
            problems.append(f"missing file {path}")
        elif hash_file(target) != digest:
            problems.append(f"modified file {path}")
    declared = set(files)
    for path in snapshot_artifact_paths(root):
        if path not in declared:
            problems.append(f"undeclared file {path}")
    return problems


# --------------------------------------------------------------------------
# The current (active) run
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ActiveRun:
    """What pre-flight found in an audit's current run. Read-only."""

    audit_dir: Path
    config: AuditConfig
    questions: list[dict[str, str]]
    states: list[QuestionState]
    evidence_files: list[str]  # "raw_responses/<name>" paths
    source_hashes: dict[str, str]
    requested_models: list[str]
    result_row_count: int = 0

    @property
    def question_count(self) -> int:
        return len(self.questions)

    @property
    def structurally_complete_count(self) -> int:
        return sum(1 for s in self.states if s.row is not None and is_structurally_complete(s.row, self._question(s)))

    def _question(self, state: QuestionState) -> dict[str, str]:
        return next(q for q in self.questions if q["question_id"] == state.question_id)

    @property
    def is_complete(self) -> bool:
        return self.structurally_complete_count == self.question_count


def _audits_root(audits_dir: str | Path | None) -> Path:
    return Path(audits_dir) if audits_dir is not None else audit_config.AUDITS_DIR


def _evidence_files(evidence_dir: Path) -> list[str]:
    """Evidence files of the current run. Dot-prefixed names (temporary
    files left by an interrupted publish) are not evidence and are skipped;
    anything else unexpected is refused."""
    if not evidence_dir.exists():
        return []
    files: list[str] = []
    for entry in sorted(evidence_dir.iterdir()):
        if entry.name.startswith("."):
            continue
        if not entry.is_file():
            raise SnapshotIntegrityError(f"Unexpected folder in {evidence_dir}: {entry.name}")
        files.append(f"{EVIDENCE_DIRNAME}/{entry.name}")
    return files


def _evidence_models(root: Path, evidence_files: list[str], questions: list[dict[str, str]], slug: str) -> list[str]:
    """The sorted distinct requested_model values of a run folder's valid
    evidence files (the existing evidence rules; invalid evidence, or a
    file matching no question, contributes no model)."""
    by_file = {f"{EVIDENCE_DIRNAME}/{q['question_id']}__gemini.json": q for q in questions}
    models: set[str] = set()
    for path in evidence_files:
        if path not in by_file:
            continue
        try:
            evidence = load_evidence(root / path, audit_slug=slug, question_row=by_file[path])
        except EvidenceIntegrityError:
            continue
        if evidence is not None:
            models.add(evidence.requested_model)
    return sorted(models)


def inspect_active_run(slug: str, *, audits_dir: str | Path | None = None) -> ActiveRun:
    """Load and check an audit's current run without writing anything.

    Raises AuditHistoryError if the config, questions or results cannot be
    loaded, question IDs are unsafe, there are duplicate Gemini rows, or an
    evidence file does not belong to a question in the question file.
    Question states (including evidence problems) are returned, not raised.
    """
    audits_root = _audits_root(audits_dir)
    try:
        config = load_audit_config(slug, audits_dir=audits_root)
    except AuditConfigError as exc:
        raise AuditHistoryError(str(exc)) from exc
    audit_dir = audits_root / slug
    try:
        questions = load_questions(str(audit_dir / QUESTIONS_FILENAME))
        validate_question_ids(questions)
        rows = load_existing_results(str(audit_dir / RESULTS_FILENAME))
    except (AuditRunnerError, WriteAuditResultError, QuestionProcessingError) as exc:
        raise AuditHistoryError(str(exc)) from exc
    duplicates = _duplicate_gemini_rows(rows)
    if duplicates:
        raise SnapshotIntegrityError(f"More than one Gemini row for: {', '.join(duplicates)}")

    evidence_dir = audit_dir / EVIDENCE_DIRNAME
    evidence_files = _evidence_files(evidence_dir)
    by_file = {f"{EVIDENCE_DIRNAME}/{q['question_id']}__gemini.json": q for q in questions}
    orphans = [path for path in evidence_files if path not in by_file]
    if orphans:
        raise SnapshotIntegrityError(
            f"Evidence files that match no question in {QUESTIONS_FILENAME}: {', '.join(orphans)}"
        )

    states = [classify_question(q, rows, evidence_dir=evidence_dir, audit_slug=config.slug) for q in questions]
    # Invalid evidence contributes no model (and blocks a snapshot via state F).
    models = _evidence_models(audit_dir, evidence_files, questions, config.slug)

    source_paths = [*SOURCE_FILES, *evidence_files]
    return ActiveRun(
        audit_dir=audit_dir,
        config=config,
        questions=questions,
        states=states,
        evidence_files=evidence_files,
        source_hashes=build_hash_map(audit_dir, source_paths),
        requested_models=models,
        result_row_count=len(rows),
    )


# --------------------------------------------------------------------------
# Snapshot validation
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SnapshotInfo:
    run_id: str
    path: Path
    manifest: dict | None
    problems: list[str]

    @property
    def is_valid(self) -> bool:
        return not self.problems

    def source_hashes(self) -> dict[str, str]:
        files = (self.manifest or {}).get("files", {})
        return {path: digest for path, digest in files.items() if not path.startswith(f"{REPORTS_DIRNAME}/")}


def _check_manifest_fields(manifest: object, *, slug: str, run_id: str) -> list[str]:
    if not isinstance(manifest, dict):
        return ["manifest is not a JSON object"]
    missing = set(MANIFEST_FIELDS) - set(manifest)
    unexpected = set(manifest) - set(MANIFEST_FIELDS)
    if missing or unexpected:
        return [f"manifest fields missing {sorted(missing)} / unexpected {sorted(unexpected)}"]
    problems: list[str] = []
    version = manifest["format_version"]
    if isinstance(version, bool) or version != MANIFEST_FORMAT_VERSION:
        problems.append(f"unsupported format_version {version!r}")
    if manifest["audit_slug"] != slug:
        problems.append(f"audit_slug {manifest['audit_slug']!r} is not {slug!r}")
    if manifest["run_id"] != run_id:
        problems.append(f"run_id {manifest['run_id']!r} does not match its folder {run_id!r}")
    try:
        expected_created_at = created_at_for(run_id)
    except AuditHistoryError as exc:
        problems.append(str(exc))
    else:
        if manifest["created_at"] != expected_created_at:
            problems.append(f"created_at {manifest['created_at']!r} does not match run_id")
    if not isinstance(manifest["signalscope_version"], str) or not manifest["signalscope_version"].strip():
        problems.append("signalscope_version must be a non-empty string")
    if manifest["status"] not in (STATUS_COMPLETE, STATUS_PARTIAL):
        problems.append(f"invalid status {manifest['status']!r}")
    total, complete = manifest["question_count"], manifest["structurally_complete_count"]
    if any(isinstance(v, bool) or not isinstance(v, int) for v in (total, complete)):
        problems.append("question counts must be integers")
    elif not (total >= 1 and 1 <= complete <= total):
        problems.append(f"invalid question counts {complete}/{total}")
    elif (manifest["status"] == STATUS_COMPLETE) != (complete == total):
        problems.append(f"status {manifest['status']!r} does not match {complete}/{total} complete")
    models = manifest["requested_models"]
    if (
        not isinstance(models, list)
        or any(not isinstance(m, str) or not m.strip() for m in models)
        or models != sorted(set(models))
    ):
        problems.append("requested_models must be a sorted list of distinct non-empty strings")
    files = manifest["files"]
    if not isinstance(files, dict):
        problems.append("files must be a mapping")
    else:
        for required in REQUIRED_SNAPSHOT_FILES:
            if required not in files:
                problems.append(f"required file {required} is not declared")
    return problems


def _structurally_complete_rows(
    root: Path, questions: list[dict[str, str]], rows: list[dict[str, str]], slug: str
) -> dict[str, dict[str, str]]:
    """The one Gemini row of each structurally complete question in a run
    folder, keyed by question ID in question-file order (the v2.3
    definition; Perplexity and incomplete rows never qualify)."""
    evidence_dir = root / EVIDENCE_DIRNAME
    complete: dict[str, dict[str, str]] = {}
    for q in questions:
        state = classify_question(q, rows, evidence_dir=evidence_dir, audit_slug=slug)
        if state.row is not None and is_structurally_complete(state.row, q):
            complete[q["question_id"]] = state.row
    return complete


def _check_snapshot_sources(root: Path, manifest: dict, slug: str) -> list[str]:
    """Load the snapshot's own source copies and recompute its coverage
    and requested models."""
    try:
        data = json.loads((root / CONFIG_FILENAME).read_text(encoding="utf-8-sig"))
        config = validate_audit_config_data(data, source=str(root / CONFIG_FILENAME))
        if config.slug != slug:
            return [f"snapshot config slug {config.slug!r} is not {slug!r}"]
        questions = load_questions(str(root / QUESTIONS_FILENAME))
        rows = load_existing_results(str(root / RESULTS_FILENAME))
    except (OSError, json.JSONDecodeError, AuditConfigError, AuditRunnerError, WriteAuditResultError) as exc:
        return [f"snapshot source files are invalid: {exc}"]
    complete = len(_structurally_complete_rows(root, questions, rows, slug))
    problems = []
    if manifest.get("question_count") != len(questions):
        problems.append(f"question_count does not match the snapshot's {len(questions)} questions")
    if manifest.get("structurally_complete_count") != complete:
        problems.append(f"structurally_complete_count does not match the snapshot's {complete} complete results")
    try:
        evidence_files = _evidence_files(root / EVIDENCE_DIRNAME)
    except SnapshotIntegrityError as exc:
        return problems + [str(exc)]
    models = _evidence_models(root, evidence_files, questions, slug)
    if manifest.get("requested_models") != models:
        problems.append(
            f"manifest requested_models {manifest.get('requested_models')!r} does not match the snapshot "
            f"evidence {models!r}"
        )
    return problems


def _validate_snapshot(root: Path, *, slug: str, run_id: str) -> SnapshotInfo:
    """Full validation of a snapshot folder expected to hold run_id: the
    run ID, every manifest field, every declared hash (and no undeclared
    file), and the snapshot's own config, questions, results and coverage.
    Used on the staging folder before publishing and on published
    snapshots. Returns every problem found; never raises for bad data."""
    try:
        parse_run_id(run_id)
    except AuditHistoryError as exc:
        return SnapshotInfo(run_id, root, None, [str(exc)])
    try:
        manifest = json.loads((root / MANIFEST_FILENAME).read_bytes().decode("utf-8"))
    except FileNotFoundError:
        return SnapshotInfo(run_id, root, None, ["manifest is missing"])
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return SnapshotInfo(run_id, root, None, [f"manifest cannot be read: {exc}"])

    problems = _check_manifest_fields(manifest, slug=slug, run_id=run_id)
    if isinstance(manifest, dict) and isinstance(manifest.get("files"), dict):
        problems += verify_hash_map(root, manifest["files"])
    if not problems:
        problems += _check_snapshot_sources(root, manifest, slug)
    return SnapshotInfo(run_id, root, manifest if isinstance(manifest, dict) else None, problems)


def inspect_snapshot(snapshot_dir: Path, *, slug: str) -> SnapshotInfo:
    """Validate a published snapshot (its folder name is its run ID). A
    snapshot with problems must not be used as historical evidence."""
    return _validate_snapshot(snapshot_dir, slug=slug, run_id=snapshot_dir.name)


def list_snapshots(slug: str, *, audits_dir: str | Path | None = None) -> list[SnapshotInfo]:
    """Every published snapshot of an audit, ordered by run ID, each with
    its validation result. Staging folders are ignored. Read-only."""
    snapshots_dir = _audits_root(audits_dir) / slug / SNAPSHOTS_DIRNAME
    if not snapshots_dir.is_dir():
        return []
    return [
        inspect_snapshot(entry, slug=slug)
        for entry in sorted(snapshots_dir.iterdir(), key=lambda p: p.name)
        if entry.is_dir() and not entry.name.startswith(".")
    ]


# --------------------------------------------------------------------------
# Snapshot creation
# --------------------------------------------------------------------------


def _serialise_manifest(manifest: dict) -> str:
    return json.dumps({field: manifest[field] for field in MANIFEST_FIELDS}, indent=2, ensure_ascii=False) + "\n"


def _render_reports(root: Path, run_date: date) -> None:
    """Render the frozen reports from the snapshot's own copies."""
    data = json.loads((root / CONFIG_FILENAME).read_text(encoding="utf-8-sig"))
    config = validate_audit_config_data(data, source=str(root / CONFIG_FILENAME))
    questions, results = str(root / QUESTIONS_FILENAME), str(root / RESULTS_FILENAME)
    generate_report(questions, results, str(root / AUDIT_REPORT_PATH), run_date, audit_config=config)
    generate_geo_findings(questions, results, str(root / FINDINGS_REPORT_PATH), run_date, audit_config=config)


def create_snapshot(
    slug: str,
    *,
    audits_dir: str | Path | None = None,
    allow_partial: bool = False,
    now: Callable[[], datetime] | None = None,
) -> SnapshotInfo:
    """Preserve the audit's current run as snapshots/<run-id>/.

    Pre-flight (writes nothing): the current run must load, have no
    evidence problems, have at least one structurally complete Gemini
    result, be complete unless allow_partial, and not already be preserved
    in any valid snapshot. The snapshot is then built in a staging folder,
    checked and published with one rename; the current run is only read,
    and any failure leaves no snapshot and no staging folder behind.
    Raises AuditHistoryError / SnapshotIntegrityError, or OSError for
    filesystem failures. Never calls Gemini.
    """
    if _retirement_dirs(_audits_root(audits_dir) / slug / SNAPSHOTS_DIRNAME):
        raise AuditHistoryError(
            "An interrupted new-run has not finished; run new-run again to complete it before snapshotting."
        )
    active = inspect_active_run(slug, audits_dir=audits_dir)

    integrity = [s for s in active.states if s.state == STATE_EVIDENCE_INTEGRITY_ERROR]
    if integrity:
        details = "; ".join(f"{s.question_id}: {s.detail}" for s in integrity)
        raise SnapshotIntegrityError(f"Cannot snapshot a run with evidence problems - {details}")
    complete = active.structurally_complete_count
    if complete == 0:
        raise AuditHistoryError("Cannot snapshot a run with no structurally complete Gemini results.")
    if not active.is_complete and not allow_partial:
        raise AuditHistoryError(
            f"The current run is partial ({complete} of {active.question_count} questions structurally complete). "
            "Use --allow-partial to preserve it as a partial snapshot."
        )

    existing = list_snapshots(slug, audits_dir=audits_dir)
    for snapshot in existing:
        if snapshot.is_valid and snapshot.source_hashes() == active.source_hashes:
            raise AuditHistoryError(f"The current run is already snapshotted as {snapshot.run_id}.")

    run_id = run_id_for((now or _utc_now)())
    snapshots_dir = active.audit_dir / SNAPSHOTS_DIRNAME
    final = snapshots_dir / run_id
    if final.exists():
        raise AuditHistoryError(f"Snapshot {run_id} already exists; refusing to overwrite it.")

    created_container = not snapshots_dir.exists()
    snapshots_dir.mkdir(exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f"{STAGING_PREFIX}{run_id}-", dir=snapshots_dir))
    try:
        for name in SOURCE_FILES:
            shutil.copyfile(active.audit_dir / name, staging / name)
        if active.evidence_files:
            (staging / EVIDENCE_DIRNAME).mkdir()
            for path in active.evidence_files:
                shutil.copyfile(active.audit_dir / path, staging / path)

        if build_hash_map(staging, list(active.source_hashes)) != active.source_hashes:
            raise SnapshotIntegrityError("Copied source files do not match the current run.")

        (staging / REPORTS_DIRNAME).mkdir()
        try:
            _render_reports(staging, parse_run_id(run_id).date())
        except (AuditConfigError, AuditRunnerError, WriteAuditResultError, ReportGeneratorError, ValueError) as exc:
            raise AuditHistoryError(f"Could not render the snapshot reports: {exc}") from exc

        manifest = {
            "format_version": MANIFEST_FORMAT_VERSION,
            "audit_slug": slug,
            "run_id": run_id,
            "created_at": created_at_for(run_id),
            "signalscope_version": SIGNALSCOPE_VERSION,
            "status": STATUS_COMPLETE if active.is_complete else STATUS_PARTIAL,
            "question_count": active.question_count,
            "structurally_complete_count": complete,
            "requested_models": active.requested_models,
            "files": build_hash_map(staging, snapshot_artifact_paths(staging)),
        }
        with (staging / MANIFEST_FILENAME).open("x", encoding="utf-8", newline="") as handle:
            handle.write(_serialise_manifest(manifest))

        staged = _validate_snapshot(staging, slug=slug, run_id=run_id)
        if not staged.is_valid:
            raise SnapshotIntegrityError("Staged snapshot failed validation: " + "; ".join(staged.problems))
        if build_hash_map(active.audit_dir, list(active.source_hashes)) != active.source_hashes:
            raise SnapshotIntegrityError("The current run changed while the snapshot was being created.")

        if final.exists():
            raise AuditHistoryError(f"Snapshot {run_id} already exists; refusing to overwrite it.")
        _publish(staging, final)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        if created_container and snapshots_dir.is_dir() and not any(snapshots_dir.iterdir()):
            snapshots_dir.rmdir()

    return inspect_snapshot(final, slug=slug)


def _publish(staging: Path, final: Path) -> None:
    # Same-filesystem rename inside snapshots/; refuses an existing target
    # on Windows, and the caller re-checks immediately beforehand.
    staging.rename(final)


# --------------------------------------------------------------------------
# Current run state
# --------------------------------------------------------------------------


def _retirement_dirs(snapshots_dir: Path) -> list[Path]:
    if not snapshots_dir.is_dir():
        return []
    return sorted(p for p in snapshots_dir.iterdir() if p.name.startswith(RETIRED_PREFIX))


def _is_fresh(active: ActiveRun) -> bool:
    return active.result_row_count == 0 and not active.evidence_files


@dataclass(frozen=True)
class ActiveRunState:
    state: str
    detail: str
    active: ActiveRun | None


def active_run_state(slug: str, *, audits_dir: str | Path | None = None) -> ActiveRunState:
    """Derive the current run's state from the files themselves - there is
    no active-run manifest. Read-only.

      reset interrupted  a retirement folder from an unfinished new-run exists
      fresh              no result rows (of any engine) and no evidence
      snapshotted        source files identical to the latest snapshot, which is valid
      complete           every question structurally complete, not yet snapshotted
      in progress / partial  anything else
    Raises AuditHistoryError if the current run cannot be read.
    """
    snapshots_dir = _audits_root(audits_dir) / slug / SNAPSHOTS_DIRNAME
    retired = _retirement_dirs(snapshots_dir)
    if retired:
        return ActiveRunState(STATE_RESET_INTERRUPTED, "run new-run again to finish the reset", None)
    active = inspect_active_run(slug, audits_dir=audits_dir)
    if _is_fresh(active):
        return ActiveRunState(STATE_FRESH, "no results or evidence yet", active)
    snapshots = list_snapshots(slug, audits_dir=audits_dir)
    if snapshots and snapshots[-1].is_valid and snapshots[-1].source_hashes() == active.source_hashes:
        return ActiveRunState(STATE_SNAPSHOTTED, f"preserved as {snapshots[-1].run_id}", active)
    if active.is_complete:
        return ActiveRunState(STATE_COMPLETE, "not snapshotted", active)
    return ActiveRunState(STATE_IN_PROGRESS, "not snapshotted", active)


# --------------------------------------------------------------------------
# New run
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class NewRunResult:
    preserved_run_id: str
    retired_evidence_files: int
    recovered: bool


def _raw_hashes(hashes: dict[str, str]) -> dict[str, str]:
    prefix = f"{EVIDENCE_DIRNAME}/"
    return {path: digest for path, digest in hashes.items() if path.startswith(prefix)}


def _retired_hashes(retired: Path) -> dict[str, str]:
    """Hashes of a retirement folder's evidence, keyed as raw_responses/<name>.
    Dot-prefixed temporary files are not evidence; a sub-folder is an error."""
    hashes: dict[str, str] = {}
    for entry in sorted(retired.iterdir()):
        if entry.name.startswith("."):
            continue
        if not entry.is_file():
            raise SnapshotIntegrityError(f"Unexpected folder in retired evidence {retired}: {entry.name}")
        hashes[f"{EVIDENCE_DIRNAME}/{entry.name}"] = hash_file(entry)
    return hashes


def _verify_retired(retired: Path, snapshot: SnapshotInfo) -> None:
    """A retirement folder may be trusted (and later deleted) only if it
    belongs to the latest snapshot and holds exactly its evidence."""
    match = _RETIRED_NAME_PATTERN.fullmatch(retired.name)
    if not match or match.group(1) != snapshot.run_id:
        raise SnapshotIntegrityError(
            f"Retired evidence folder {retired.name} does not belong to the latest snapshot {snapshot.run_id}; "
            "it has been left in place for investigation."
        )
    if _retired_hashes(retired) != _raw_hashes(snapshot.source_hashes()):
        raise SnapshotIntegrityError(
            f"Retired evidence in {retired.name} does not match snapshot {snapshot.run_id}; "
            "it has been left in place for investigation."
        )


def _retire(raw_dir: Path, retired: Path) -> None:
    # Same-filesystem rename into snapshots/; the target never exists yet.
    raw_dir.rename(retired)


def _write_fresh_results(results_path: Path) -> None:
    write_results_atomically(str(results_path), [])


def _validate_fresh_results(results_path: Path) -> None:
    try:
        rows = load_existing_results(str(results_path))
    except WriteAuditResultError as exc:
        raise SnapshotIntegrityError(f"The reset {RESULTS_FILENAME} is not valid: {exc}") from exc
    if rows:
        raise SnapshotIntegrityError(f"The reset {RESULTS_FILENAME} still contains {len(rows)} row(s).")


def _remove_retired(retired: Path) -> None:
    shutil.rmtree(retired)


def _verify_final_state(audit_dir: Path, expected: dict[str, str]) -> None:
    problems = []
    for name in (CONFIG_FILENAME, QUESTIONS_FILENAME):
        if hash_file(audit_dir / name) != expected[name]:
            problems.append(f"{name} changed")
    if (audit_dir / EVIDENCE_DIRNAME).exists():
        problems.append(f"{EVIDENCE_DIRNAME}/ exists")
    if _retirement_dirs(audit_dir / SNAPSHOTS_DIRNAME):
        problems.append("a retirement folder remains")
    try:
        _validate_fresh_results(audit_dir / RESULTS_FILENAME)
    except SnapshotIntegrityError as exc:
        problems.append(str(exc))
    if problems:
        raise SnapshotIntegrityError("The new run is not fresh after reset: " + "; ".join(problems))


def start_new_run(slug: str, *, audits_dir: str | Path | None = None) -> NewRunResult:
    """Clear the current run's results and evidence so a new run can be
    collected - only once the latest snapshot is valid and preserves the
    current run exactly. The config and questions are never touched.

    Reset order: retire raw_responses/ into a hidden folder inside
    snapshots/ (one rename), check the results file still matches the
    snapshot, reset it to its header with the existing writer, check it,
    delete the retired evidence (verified against the snapshot first),
    and check the final state is fresh. If a previous new-run was
    interrupted, its retirement folder is verified and the reset is
    finished. Never calls Gemini. Raises AuditHistoryError /
    SnapshotIntegrityError, or OSError for filesystem failures; the latest
    snapshot always holds the complete previous run.
    """
    audit_dir = _audits_root(audits_dir) / slug
    snapshots_dir = audit_dir / SNAPSHOTS_DIRNAME
    raw_dir = audit_dir / EVIDENCE_DIRNAME
    results_path = audit_dir / RESULTS_FILENAME

    retired_dirs = _retirement_dirs(snapshots_dir)
    if len(retired_dirs) > 1:
        raise SnapshotIntegrityError(
            f"More than one retired evidence folder exists ({', '.join(p.name for p in retired_dirs)}); "
            "refusing to guess which belongs to the latest snapshot."
        )
    retired = retired_dirs[0] if retired_dirs else None

    active = inspect_active_run(slug, audits_dir=audits_dir)  # config, questions and results must load
    if retired is None and _is_fresh(active):
        raise AuditHistoryError("The current run is already fresh; there is nothing to reset.")

    snapshots = list_snapshots(slug, audits_dir=audits_dir)
    if not snapshots:
        raise AuditHistoryError("The current run has not been snapshotted; run snapshot first.")
    latest = snapshots[-1]
    if not latest.is_valid:
        raise SnapshotIntegrityError(
            f"The latest snapshot {latest.run_id} failed validation ({'; '.join(latest.problems)}); "
            "resolve the history before starting a new run."
        )
    expected = latest.source_hashes()

    for name in (CONFIG_FILENAME, QUESTIONS_FILENAME):
        if hash_file(audit_dir / name) != expected[name]:
            raise AuditHistoryError(
                f"{name} has changed since snapshot {latest.run_id}; snapshot the current run first."
            )

    recovered = retired is not None
    if retired is None:
        if active.source_hashes != expected:
            raise AuditHistoryError(
                f"The current run differs from the latest snapshot {latest.run_id}; snapshot the current run first."
            )
        # Final re-check immediately before anything is changed.
        if build_hash_map(audit_dir, list(expected)) != expected or _evidence_files(raw_dir) != sorted(
            _raw_hashes(expected)
        ):
            raise AuditHistoryError("The current run changed during checks; nothing was reset.")
        if raw_dir.exists():
            snapshots_dir.mkdir(exist_ok=True)
            retired = snapshots_dir / f"{RETIRED_PREFIX}{latest.run_id}-{secrets.token_hex(4)}"
            _retire(raw_dir, retired)
    else:
        _verify_retired(retired, latest)
        if raw_dir.exists():
            raise SnapshotIntegrityError(
                f"New evidence appeared in {EVIDENCE_DIRNAME}/ during an interrupted new-run; refusing to continue."
            )

    if retired is not None:
        _verify_retired(retired, latest)
    if raw_dir.exists():
        raise SnapshotIntegrityError(f"An unexpected {EVIDENCE_DIRNAME}/ folder appeared; refusing to continue.")

    results_hash = hash_file(results_path)
    if results_hash == expected[RESULTS_FILENAME]:
        _write_fresh_results(results_path)
    elif not (recovered and active.result_row_count == 0):
        raise SnapshotIntegrityError(
            f"{RESULTS_FILENAME} matches neither snapshot {latest.run_id} nor a fresh results file; "
            "refusing to continue."
        )
    _validate_fresh_results(results_path)

    retired_count = 0
    if retired is not None:
        _verify_retired(retired, latest)
        retired_count = len(_raw_hashes(expected))
        _remove_retired(retired)

    _verify_final_state(audit_dir, expected)
    return NewRunResult(latest.run_id, retired_count, recovered)


# --------------------------------------------------------------------------
# Comparison of two snapshots
# --------------------------------------------------------------------------

COMPARISONS_DIRNAME = "comparisons"
PROGRESS_FILENAME = "GEO_PROGRESS.md"
# Config fields that define what is measured. company_name, report_subject
# and question_library are display labels only (the question library itself
# is compared question by question).
CORE_CONFIG_FIELDS = ("slug", "brand", "market", "category", "competitors")


class NotComparableError(AuditHistoryError):
    """Two snapshots do not share the methodology needed for comparison."""

    def __init__(self, message: str, problems: list[str]) -> None:
        super().__init__(message + " " + "; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class _LoadedSnapshot:
    info: SnapshotInfo
    config: AuditConfig
    questions: list[dict[str, str]]
    complete_rows: dict[str, dict[str, str]]


@dataclass(frozen=True)
class ComparisonResult:
    audit_slug: str
    from_run: str
    to_run: str
    from_total: int
    from_complete: int
    to_total: int
    to_complete: int
    shared_question_ids: tuple[str, ...]
    requested_model_warning: str | None
    version_warning: str | None
    progress: Progress
    output_path: Path

    @property
    def shared_question_count(self) -> int:
        return len(self.shared_question_ids)


def _reports_root(reports_dir: str | Path | None, audits_dir: str | Path | None) -> Path:
    # reports/ sits next to audits/, so a comparison of an audit in a
    # temporary audits folder never writes into the real reports/.
    return Path(reports_dir) if reports_dir is not None else _audits_root(audits_dir).parent / "reports"


def comparison_output_path(slug: str, from_run: str, to_run: str, *, reports_dir: Path) -> Path:
    return reports_dir / slug / COMPARISONS_DIRNAME / f"{from_run}__{to_run}" / PROGRESS_FILENAME


def _load_snapshot_for_comparison(snapshots_dir: Path, run_id: str, slug: str, side: str) -> _LoadedSnapshot:
    path = snapshots_dir / run_id
    if not path.is_dir():
        raise AuditHistoryError(f"No snapshot {run_id} for audit {slug} ({side} run).")
    info = inspect_snapshot(path, slug=slug)
    if not info.is_valid:
        raise SnapshotIntegrityError(
            f"Snapshot {run_id} ({side} run) failed validation and cannot be compared: {'; '.join(info.problems)}"
        )
    try:
        data = json.loads((path / CONFIG_FILENAME).read_text(encoding="utf-8-sig"))
        config = validate_audit_config_data(data, source=str(path / CONFIG_FILENAME))
        questions = load_questions(str(path / QUESTIONS_FILENAME))
        rows = load_existing_results(str(path / RESULTS_FILENAME))
    except (OSError, json.JSONDecodeError, AuditConfigError, AuditRunnerError, WriteAuditResultError) as exc:
        raise SnapshotIntegrityError(f"Snapshot {run_id} ({side} run) cannot be read: {exc}") from exc
    return _LoadedSnapshot(info, config, questions, _structurally_complete_rows(path, questions, rows, slug))


def _config_differences(earlier: AuditConfig, later: AuditConfig) -> list[str]:
    problems = []
    for field in CORE_CONFIG_FIELDS:
        a, b = getattr(earlier, field), getattr(later, field)
        if a == b:
            continue
        if field == "competitors":
            kind = "competitor order differs" if sorted(a) == sorted(b) else "competitors differ"
            problems.append(f"{kind} ({list(a)} vs {list(b)})")
        else:
            problems.append(f"{field} differs ({a!r} vs {b!r})")
    return problems


def _question_key(q: dict[str, str]) -> tuple[str, str, str]:
    return (q["question_id"], q["buyer_journey_stage"], q["question"])


def _question_library_differences(earlier: list[dict[str, str]], later: list[dict[str, str]]) -> list[str]:
    if [_question_key(q) for q in earlier] == [_question_key(q) for q in later]:
        return []
    ids_a = [q["question_id"] for q in earlier]
    ids_b = [q["question_id"] for q in later]
    problems = []
    removed = [i for i in ids_a if i not in set(ids_b)]
    added = [i for i in ids_b if i not in set(ids_a)]
    if removed:
        problems.append(f"questions only in the from run: {', '.join(removed)}")
    if added:
        problems.append(f"questions only in the to run: {', '.join(added)}")
    common = set(ids_a) & set(ids_b)
    if [i for i in ids_a if i in common] != [i for i in ids_b if i in common]:
        problems.append("question order differs")
    by_id_b = {q["question_id"]: q for q in later}
    for q in earlier:
        other = by_id_b.get(q["question_id"])
        if other is None:
            continue
        if q["question"] != other["question"]:
            problems.append(f"{q['question_id']} question text differs")
        if q["buyer_journey_stage"] != other["buyer_journey_stage"]:
            problems.append(f"{q['question_id']} buyer_journey_stage differs")
    return problems or ["question library differs"]


def _requested_model_warning(earlier: SnapshotInfo, later: SnapshotInfo) -> str | None:
    a, b = earlier.manifest["requested_models"], later.manifest["requested_models"]
    if a == b:
        return None
    return (
        "The requested Gemini model set differs between these runs "
        f"(from run: {', '.join(a) or 'none recorded'}; to run: {', '.join(b) or 'none recorded'}). "
        "This comparison does not attribute any change to the model difference."
    )


def _version_warning(earlier: SnapshotInfo, later: SnapshotInfo) -> str | None:
    a, b = earlier.manifest["signalscope_version"], later.manifest["signalscope_version"]
    if a == b:
        return None
    return (
        f"These runs were created with different SignalScope versions (from run: {a}; to run: {b}); "
        "methodology or rendering behaviour may have changed between versions."
    )


def _write_report_atomically(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.stem}_", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)
        raise


def _check_slug_arg(slug: str) -> None:
    try:
        _check_slug(slug)
    except AuditConfigError as exc:
        raise AuditHistoryError(str(exc)) from exc


def compare_snapshots(
    slug: str,
    from_run: str,
    to_run: str,
    *,
    audits_dir: str | Path | None = None,
    reports_dir: str | Path | None = None,
    generated_at: date | None = None,
) -> ComparisonResult:
    """Measure change from an earlier snapshot to a later one of the same
    audit, and write the derived GEO_PROGRESS.md to
    reports/<slug>/comparisons/<from-run>__<to-run>/ (replacing an earlier
    comparison of the same pair).

    Both snapshots must be valid, from_run must be earlier than to_run,
    and the snapshots' own configs (core fields) and question libraries
    (ordered ID, stage and text) must match. The metrics come from
    measurement_engine.compare_audits over the Gemini questions that are
    structurally complete in both runs. Reads only the snapshots' own
    files; writes only the comparison report, and nothing at all when any
    check fails. Never calls Gemini.
    """
    _check_slug_arg(slug)
    earlier_at, later_at = parse_run_id(from_run), parse_run_id(to_run)
    if from_run == to_run:
        raise AuditHistoryError("from-run and to-run are the same run; choose two different snapshots.")
    if earlier_at > later_at:
        raise AuditHistoryError(
            f"The comparison is directional: from-run ({from_run}) must be earlier than to-run ({to_run}). "
            "Swap the two run IDs."
        )

    snapshots_dir = _audits_root(audits_dir) / slug / SNAPSHOTS_DIRNAME
    earlier = _load_snapshot_for_comparison(snapshots_dir, from_run, slug, "from")
    later = _load_snapshot_for_comparison(snapshots_dir, to_run, slug, "to")

    config_problems = _config_differences(earlier.config, later.config)
    if config_problems:
        raise NotComparableError("The two runs do not share the same core audit configuration:", config_problems)
    library_problems = _question_library_differences(earlier.questions, later.questions)
    if library_problems:
        raise NotComparableError("The two runs do not use the same question library:", library_problems)

    shared = tuple(
        q["question_id"]
        for q in later.questions
        if q["question_id"] in earlier.complete_rows and q["question_id"] in later.complete_rows
    )
    if not shared:
        raise AuditHistoryError(
            "No question is structurally complete in both runs; there is nothing comparable to measure."
        )
    from_rows = [earlier.complete_rows[qid] for qid in shared]
    to_rows = [later.complete_rows[qid] for qid in shared]
    if [r["question_id"] for r in from_rows] != list(shared) or [r["question_id"] for r in to_rows] != list(shared):
        raise SnapshotIntegrityError("The shared question sets of the two runs do not line up.")

    config = later.config
    try:
        progress = compare_audits(
            from_rows,
            to_rows,
            len(shared),
            brand=config.brand,
            market=config.market,
            category=config.category,
            generated_at=generated_at or date.today(),
        )
    except MeasurementEngineError as exc:
        raise AuditHistoryError(f"Could not compare the runs: {exc}") from exc

    model_warning = _requested_model_warning(earlier.info, later.info)
    version_warning = _version_warning(earlier.info, later.info)
    context = RunComparisonContext(
        from_run=from_run,
        to_run=to_run,
        from_complete=len(earlier.complete_rows),
        from_total=len(earlier.questions),
        to_complete=len(later.complete_rows),
        to_total=len(later.questions),
        shared_question_count=len(shared),
        requested_model_warning=model_warning,
        version_warning=version_warning,
    )
    markdown = render_markdown(progress, audit_config=config, run_context=context)

    # The snapshots must still be exactly what was validated and read.
    for loaded, side in ((earlier, "from"), (later, "to")):
        if not inspect_snapshot(loaded.info.path, slug=slug).is_valid:
            raise SnapshotIntegrityError(f"Snapshot {loaded.info.run_id} ({side} run) changed during the comparison.")

    output = comparison_output_path(slug, from_run, to_run, reports_dir=_reports_root(reports_dir, audits_dir))
    _write_report_atomically(output, markdown)
    return ComparisonResult(
        audit_slug=slug,
        from_run=from_run,
        to_run=to_run,
        from_total=context.from_total,
        from_complete=context.from_complete,
        to_total=context.to_total,
        to_complete=context.to_complete,
        shared_question_ids=shared,
        requested_model_warning=model_warning,
        version_warning=version_warning,
        progress=progress,
        output_path=output,
    )


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _active_summary(slug: str, audits_dir=None) -> str:
    try:
        state = active_run_state(slug, audits_dir=audits_dir)
    except (AuditHistoryError, OSError) as exc:
        return f"Current run: cannot be read ({exc})"
    active = state.active
    if active is None:
        return f"Current run: {state.state} - {state.detail}"
    counts = f"{active.structurally_complete_count}/{active.question_count} structurally complete"
    problems = sum(1 for s in active.states if s.state == STATE_EVIDENCE_INTEGRITY_ERROR)
    problem_note = f"; {problems} evidence problem(s)" if problems else ""
    return f"Current run: {state.state} ({counts}{problem_note}) - {state.detail}"


def _cmd_snapshot(args: argparse.Namespace) -> int:
    snapshot = create_snapshot(args.audit, allow_partial=args.allow_partial)
    manifest = snapshot.manifest
    print(f"Snapshot {snapshot.run_id} created: {snapshot.path}")
    print(f"  status: {manifest['status']} ({manifest['structurally_complete_count']}/{manifest['question_count']} "
          "structurally complete)")
    print(f"  requested models: {', '.join(manifest['requested_models']) or '(none recorded)'}")
    print(f"  files: {len(manifest['files'])} (SHA-256 recorded in {MANIFEST_FILENAME})")
    return 0


def _cmd_new_run(args: argparse.Namespace) -> int:
    result = start_new_run(args.audit)
    if result.recovered:
        print("Finished an interrupted new-run.")
    print(f"New run started for {args.audit}; the previous run is preserved in snapshot {result.preserved_run_id}.")
    print(f"  {RESULTS_FILENAME}: reset to its header")
    print(f"  {EVIDENCE_DIRNAME}/: {result.retired_evidence_files} evidence file(s) removed (kept in the snapshot)")
    return 0


def _cmd_compare(args: argparse.Namespace) -> int:
    result = compare_snapshots(args.audit, args.from_run, args.to_run)
    print(f"Compared {args.audit}: from run {result.from_run} to run {result.to_run}")
    print(f"  from coverage: {result.from_complete}/{result.from_total} structurally complete")
    print(f"  to coverage: {result.to_complete}/{result.to_total} structurally complete")
    print(f"  shared complete questions used: {result.shared_question_count}")
    for warning in (result.requested_model_warning, result.version_warning):
        if warning:
            print(f"Warning: {warning}")
    print(result.progress.overall_assessment)
    print(f"GEO progress report written to: {result.output_path}")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    snapshots = list_snapshots(args.audit)
    print(f"Audit: {args.audit}")
    if not snapshots:
        print("Snapshots: none")
    for s in snapshots:
        if s.is_valid:
            m = s.manifest
            print(
                f"  {s.run_id}  created {m['created_at']}  {m['status']}  "
                f"{m['structurally_complete_count']}/{m['question_count']} complete  "
                f"models: {', '.join(m['requested_models']) or '-'}  v{m['signalscope_version']}  integrity: OK"
            )
        else:
            print(f"  {s.run_id}  INVALID - not usable as historical evidence: {'; '.join(s.problems)}")
    print(_active_summary(args.audit))
    return 1 if any(not s.is_valid for s in snapshots) else 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SignalScope AI audit run history (snapshots).")
    commands = parser.add_subparsers(dest="command", required=True)
    snapshot = commands.add_parser("snapshot", help="Preserve the current run as an immutable snapshot")
    snapshot.add_argument("--audit", required=True, help="Audit slug under audits/")
    snapshot.add_argument(
        "--allow-partial", action="store_true", help="Allow preserving a run that is not structurally complete"
    )
    new_run = commands.add_parser(
        "new-run", help="Start a new run after the current run has been snapshotted (clears results and evidence)"
    )
    new_run.add_argument("--audit", required=True, help="Audit slug under audits/")
    compare = commands.add_parser(
        "compare", help="Measure change from an earlier snapshot to a later one (writes a derived report)"
    )
    compare.add_argument("--audit", required=True, help="Audit slug under audits/")
    compare.add_argument("--from-run", required=True, help="Run ID of the earlier snapshot")
    compare.add_argument("--to-run", required=True, help="Run ID of the later snapshot")
    listing = commands.add_parser("list", help="List snapshots and the current run's state (read-only)")
    listing.add_argument("--audit", required=True, help="Audit slug under audits/")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = parse_args(argv)
    try:
        handler = {"snapshot": _cmd_snapshot, "new-run": _cmd_new_run, "compare": _cmd_compare, "list": _cmd_list}[args.command]
        return handler(args)
    except (AuditHistoryError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

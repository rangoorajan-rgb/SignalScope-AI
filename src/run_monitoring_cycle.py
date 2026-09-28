"""Recurring monitoring cycle for SignalScope AI (v2.5).

One invocation plans (and, in a later checkpoint, runs) at most one
monitoring cycle for one audit, reusing the v2.3/v2.4 lifecycle:

    new-run -> structured batch -> snapshot (complete runs only) -> compare

This module owns no evidence, snapshot or comparison logic of its own. It
derives the audit's position in the cycle from the current run and its
snapshots (audit_history.py), checks the preconditions that must hold
before any Gemini call (no evidence problems, a valid baseline, unchanged
methodology, a configured API key when collection is needed), and holds a
per-audit OS lock so two cycles for the same audit never overlap. Time is
owned by an external scheduler; SignalScope only checks whether the latest
snapshot is at least --interval-days old.

Collection runs in chunks of CHUNK_SIZE questions and stops as soon as a
chunk makes no progress, so a persistent outage cannot spend across the
whole audit; the next external trigger resumes the run. Only a
structurally complete run is snapshotted automatically, and it is then
compared with the immediately previous snapshot using audit_history's own
comparison (reports/<slug>/comparisons/<previous>__<new>/GEO_PROGRESS.md).
A snapshot whose comparison is missing is compared on the next invocation.

    python src/run_monitoring_cycle.py --audit <slug> --interval-days N [--dry-run]
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import socket
import sys
import time
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import gemini_client
from audit_config import AuditConfigError, _check_slug
from audit_history import (
    QUESTIONS_FILENAME,
    RESULTS_FILENAME,
    STATE_COMPLETE,
    STATE_FRESH,
    STATE_IN_PROGRESS,
    STATE_RESET_INTERRUPTED,
    STATE_SNAPSHOTTED,
    AuditHistoryError,
    _audits_root,
    _config_differences,
    _load_snapshot_for_comparison,
    _question_library_differences,
    _reports_root,
    active_run_state,
    compare_snapshots,
    comparison_output_path,
    create_snapshot,
    inspect_active_run,
    list_snapshots,
    parse_run_id,
    start_new_run,
)
from audit_runner import AuditRunnerError
from run_batch_audit import DEFAULT_REQUEST_DELAY_SECONDS, is_retryable_error
from run_structured_batch_audit import (
    ACTIONABLE_STATES,
    STATE_ANSWER_STORED,
    STATE_EVIDENCE_INTEGRITY_ERROR,
    STATE_NOT_STARTED,
    StructuredBatchError,
    run_structured_batch_audit,
)
from write_single_audit_result import WriteAuditResultError
from version import SIGNALSCOPE_VERSION

LOCK_FILENAME = ".monitoring.lock"

# Outcomes of a plan (and, later, of a cycle).
OUTCOME_READY = "ready"  # the planned actions may run
OUTCOME_NOT_DUE = "not due"
OUTCOME_OPERATOR_ACTION = "operator action required"
OUTCOME_ALREADY_RUNNING = "already running"

EXIT_OK = 0
EXIT_OPERATOR_ACTION = 1
EXIT_ALREADY_RUNNING = 3
EXIT_INCOMPLETE = 4  # reserved: collection ran but the run is not yet complete

_EXIT_CODES = {
    OUTCOME_READY: EXIT_OK,
    OUTCOME_NOT_DUE: EXIT_OK,
    OUTCOME_OPERATOR_ACTION: EXIT_OPERATOR_ACTION,
    OUTCOME_ALREADY_RUNNING: EXIT_ALREADY_RUNNING,
}

# Planned steps, in execution order.
STEP_RECOVER_NEW_RUN = "recover interrupted new-run"
STEP_NEW_RUN = "new-run"
STEP_COLLECT = "collect"
STEP_SNAPSHOT_WHEN_COMPLETE = "snapshot when complete"
STEP_SNAPSHOT = "snapshot"
STEP_COMPARE = "compare"

_ALLOW_PARTIAL_NOTE = (
    "Automation never accepts a partial run; the operator may deliberately preserve it with "
    "'python src/audit_history.py snapshot --audit {slug} --allow-partial'."
)


class MonitoringError(Exception):
    """A monitoring request is invalid or cannot be planned."""


class MonitoringLockError(MonitoringError):
    """The operating system cannot provide the per-audit monitoring lock."""


class MonitoringLockHeld(MonitoringError):
    """Another process holds this audit's monitoring lock."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# Plan
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CyclePlan:
    """The one safe next action for an audit's monitoring cycle."""

    audit_slug: str
    interval_days: int
    outcome: str
    steps: tuple[str, ...] = ()
    active_state: str | None = None
    latest_snapshot: str | None = None
    previous_snapshot: str | None = None
    due: bool | None = None
    requires_collection: bool = False
    requires_api_key: bool = False
    api_key_present: bool | None = None  # checked only when collection is planned
    integrity_problems: int = 0
    methodology_differences: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    @property
    def exit_code(self) -> int:
        return _EXIT_CODES[self.outcome]

    @property
    def action(self) -> str:
        return " -> ".join(self.steps) if self.steps else "none"


def validate_interval_days(interval_days: object) -> int:
    if isinstance(interval_days, bool) or not isinstance(interval_days, int) or interval_days < 1:
        raise MonitoringError(f"interval_days must be a positive whole number of days, got {interval_days!r}.")
    return interval_days


def is_due(latest_created_at: datetime, now: datetime, interval_days: int) -> bool:
    """True when at least interval_days have passed since the latest
    snapshot. Both times must be timezone-aware; no calendar logic."""
    validate_interval_days(interval_days)
    for name, moment in (("latest_created_at", latest_created_at), ("now", now)):
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise MonitoringError(f"{name} must be timezone-aware.")
    return now - latest_created_at >= timedelta(days=interval_days)


def gemini_api_key_present() -> bool:
    """Whether a Gemini API key is configured, read from the same source
    gemini_client uses (the environment, then the project .env). Never
    returns, prints or validates the key, and makes no API call."""
    gemini_client._load_dotenv(gemini_client.ENV_FILE)
    return bool(os.environ.get("GEMINI_API_KEY"))


def plan_cycle(
    slug: str,
    interval_days: int,
    *,
    audits_dir: str | Path | None = None,
    reports_dir: str | Path | None = None,
    now: Callable[[], datetime] | None = None,
    api_key_present: Callable[[], bool] | None = None,
) -> CyclePlan:
    """Decide the one safe next action for an audit's monitoring cycle.

    Read-only: never calls Gemini, never writes a file, never takes the
    lock. The API key is checked only when the plan needs collection.
    Raises MonitoringError for an invalid slug or interval; every audit
    problem is returned as an operator-action plan.
    """
    try:
        _check_slug(slug)
    except AuditConfigError as exc:
        raise MonitoringError(str(exc)) from exc
    validate_interval_days(interval_days)
    moment = (now or _utc_now)()
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise MonitoringError("now must be timezone-aware.")
    key_check = api_key_present or gemini_api_key_present

    def plan(outcome: str, *reasons: str, **fields) -> CyclePlan:
        return CyclePlan(audit_slug=slug, interval_days=interval_days, outcome=outcome, reasons=reasons, **fields)

    def stop(*reasons: str, **fields) -> CyclePlan:
        return plan(OUTCOME_OPERATOR_ACTION, *reasons, **fields)

    # 1. The current run must be readable, with no evidence problems.
    try:
        active = inspect_active_run(slug, audits_dir=audits_dir)
    except AuditHistoryError as exc:
        return stop(f"The current run cannot be inspected: {exc}")
    integrity = [s for s in active.states if s.state == STATE_EVIDENCE_INTEGRITY_ERROR]
    if integrity:
        details = "; ".join(f"{s.question_id}: {s.detail}" for s in integrity)
        return stop(
            f"Evidence integrity problems must be investigated by the operator: {details}",
            integrity_problems=len(integrity),
        )

    # 2. A valid baseline, and the latest snapshot valid (no fallback).
    snapshots = list_snapshots(slug, audits_dir=audits_dir)
    if not snapshots:
        return stop(
            "No snapshot exists. Complete, review and snapshot the baseline run manually "
            "(python src/audit_history.py snapshot) before recurring monitoring can begin."
        )
    latest = snapshots[-1]
    previous = snapshots[-2] if len(snapshots) > 1 else None
    ids = {"latest_snapshot": latest.run_id, "previous_snapshot": previous.run_id if previous else None}
    if not latest.is_valid:
        return stop(
            f"The latest snapshot {latest.run_id} failed validation ({'; '.join(latest.problems)}); "
            "it is never skipped in favour of an older one.",
            **ids,
        )

    try:
        state = active_run_state(slug, audits_dir=audits_dir).state
    except AuditHistoryError as exc:
        return stop(f"The current run state cannot be derived: {exc}", **ids)
    due = is_due(parse_run_id(latest.run_id), moment, interval_days)
    known = {**ids, "active_state": state, "due": due}

    def methodology_check() -> tuple[str, ...]:
        loaded = _load_snapshot_for_comparison(latest.path.parent, latest.run_id, slug, "latest")
        return tuple(
            _config_differences(loaded.config, active.config)
            + _question_library_differences(loaded.questions, active.questions)
        )

    def collection_plan(steps: tuple[str, ...], reason: str) -> CyclePlan:
        try:
            differences = methodology_check()
        except AuditHistoryError as exc:
            return stop(f"The latest snapshot cannot be read for the methodology check: {exc}", **known)
        if differences:
            return stop(
                "The current configuration or question library differs from the latest snapshot; "
                "collection would not be comparable. Restore the methodology or establish a new baseline.",
                methodology_differences=differences,
                **known,
            )
        present = key_check()
        if not present:
            return stop(
                "Collection is required but no Gemini API key is configured (GEMINI_API_KEY); "
                "nothing was changed.",
                requires_collection=True,
                requires_api_key=True,
                api_key_present=False,
                **known,
            )
        return plan(
            OUTCOME_READY,
            reason,
            steps=steps,
            requires_collection=True,
            requires_api_key=True,
            api_key_present=True,
            **known,
        )

    # 3. The start-state matrix.
    if state == STATE_RESET_INTERRUPTED:
        return collection_plan(
            (STEP_RECOVER_NEW_RUN, STEP_COLLECT, STEP_SNAPSHOT_WHEN_COMPLETE, STEP_COMPARE),
            "A new-run was interrupted; the cycle finishes it with the v2.4 recovery, then collects.",
        )
    if state == STATE_FRESH:
        return collection_plan(
            (STEP_COLLECT, STEP_SNAPSHOT_WHEN_COMPLETE, STEP_COMPARE),
            "The current run is fresh; the cycle collects it.",
        )
    if state == STATE_IN_PROGRESS:
        actionable = [s for s in active.states if s.state in ACTIONABLE_STATES]
        if not actionable:
            return stop(
                f"The current run is partial ({active.structurally_complete_count} of {active.question_count} "
                "structurally complete) and no question can be collected automatically.",
                _ALLOW_PARTIAL_NOTE.format(slug=slug),
                **known,
            )
        return collection_plan(
            (STEP_COLLECT, STEP_SNAPSHOT_WHEN_COMPLETE, STEP_COMPARE),
            f"The current run is in progress; {len(actionable)} question(s) can still be collected.",
        )
    if state == STATE_COMPLETE:
        duplicate = next(
            (s for s in snapshots if s.is_valid and s.source_hashes() == active.source_hashes), None
        )
        if duplicate is not None:
            return stop(
                f"The current run is identical to snapshot {duplicate.run_id}, which is not the latest snapshot.",
                **known,
            )
        try:
            differences = methodology_check()
        except AuditHistoryError as exc:
            return stop(f"The latest snapshot cannot be read for the methodology check: {exc}", **known)
        if differences:
            return stop(
                "The complete current run does not share the latest snapshot's methodology, so it could "
                "not be compared. Snapshot it manually if it should be preserved.",
                methodology_differences=differences,
                **known,
            )
        return plan(
            OUTCOME_READY,
            "The current run is complete but not snapshotted; no Gemini call is needed.",
            steps=(STEP_SNAPSHOT, STEP_COMPARE),
            **known,
        )

    if state != STATE_SNAPSHOTTED:
        return stop(f"Unrecognised current-run state {state!r}.", **known)
    # Snapshotted: the current run is the latest snapshot.
    notes: list[str] = []
    if previous is not None:
        if not previous.is_valid:
            return stop(
                f"The previous snapshot {previous.run_id} failed validation ({'; '.join(previous.problems)}); "
                f"the comparison {previous.run_id} -> {latest.run_id} cannot be made.",
                **known,
            )
        try:
            earlier = _load_snapshot_for_comparison(latest.path.parent, previous.run_id, slug, "previous")
            later = _load_snapshot_for_comparison(latest.path.parent, latest.run_id, slug, "latest")
        except AuditHistoryError as exc:
            return stop(f"The snapshots cannot be read for comparison: {exc}", **known)
        comparable = not (
            _config_differences(earlier.config, later.config)
            or _question_library_differences(earlier.questions, later.questions)
        )
        if not comparable:
            notes.append(
                f"Snapshot {latest.run_id} does not share snapshot {previous.run_id}'s methodology, so it "
                "starts a new baseline; no comparison is expected between them."
            )
        else:
            report = comparison_output_path(
                slug, previous.run_id, latest.run_id, reports_dir=_reports_root(reports_dir, audits_dir)
            )
            if not report.is_file():
                return plan(
                    OUTCOME_READY,
                    f"The comparison {previous.run_id} -> {latest.run_id} has not been produced yet.",
                    steps=(STEP_COMPARE,),
                    **known,
                )
    else:
        notes.append(f"Snapshot {latest.run_id} is the baseline; there is no earlier run to compare with.")

    if not due:
        return plan(
            OUTCOME_NOT_DUE,
            *notes,
            f"The latest snapshot {latest.run_id} is less than {interval_days} day(s) old.",
            **known,
        )
    result = collection_plan(
        (STEP_NEW_RUN, STEP_COLLECT, STEP_SNAPSHOT_WHEN_COMPLETE, STEP_COMPARE),
        f"The latest snapshot {latest.run_id} is at least {interval_days} day(s) old; a new cycle is due.",
    )
    return replace(result, reasons=(*notes, *result.reasons))


# --------------------------------------------------------------------------
# Per-audit lock
# --------------------------------------------------------------------------

# The locked byte lies far beyond the metadata, so other processes can still
# read the metadata on Windows (msvcrt locks are mandatory byte ranges).
_LOCK_OFFSET = 0x7FFFFFFF
_CONTENTION_ERRNOS = {errno.EACCES, errno.EAGAIN, getattr(errno, "EDEADLK", -1), getattr(errno, "EDEADLOCK", -1)}

if os.name == "nt":
    import msvcrt

    def _os_try_lock(fd: int) -> None:
        os.lseek(fd, _LOCK_OFFSET, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

    def _os_unlock(fd: int) -> None:
        os.lseek(fd, _LOCK_OFFSET, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    try:
        import fcntl
    except ImportError:  # pragma: no cover - no supported lock on this platform
        fcntl = None

    def _os_try_lock(fd: int) -> None:
        if fcntl is None:
            raise MonitoringLockError("This platform provides no supported file lock (fcntl).")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _os_unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


def lock_path(slug: str, *, audits_dir: str | Path | None = None) -> Path:
    try:
        _check_slug(slug)
    except AuditConfigError as exc:
        raise MonitoringError(str(exc)) from exc
    return _audits_root(audits_dir) / slug / LOCK_FILENAME


def _try_lock(fd: int, path: Path) -> None:
    try:
        _os_try_lock(fd)
    except MonitoringLockError:
        raise
    except OSError as exc:
        if isinstance(exc, BlockingIOError) or exc.errno in _CONTENTION_ERRNOS:
            raise MonitoringLockHeld(f"Another monitoring cycle holds {path}.") from exc
        raise MonitoringLockError(f"Could not lock {path}: {exc}") from exc


class AuditLock:
    """The per-audit monitoring lock: an OS lock held on
    audits/<slug>/.monitoring.lock for as long as this object holds it.

    The kernel releases it if the process dies, so there is no stale-lock
    handling: the file may remain and is simply reused. The metadata
    written into the file is for people only and is never read to decide
    anything. Acquisition never waits: MonitoringLockHeld if another
    process holds it, MonitoringLockError if no lock can be provided."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._fd: int | None = None

    @property
    def held(self) -> bool:
        return self._fd is not None

    def acquire(self, slug: str) -> None:
        if self._fd is not None:
            raise MonitoringError(f"{self.path} is already held by this process.")
        try:
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o644)
        except OSError as exc:
            raise MonitoringLockError(f"Could not open {self.path}: {exc}") from exc
        try:
            _try_lock(fd, self.path)
        except BaseException:
            os.close(fd)
            raise
        self._fd = fd
        try:
            self._write_metadata(slug)
        except OSError as exc:
            self.release()
            raise MonitoringLockError(f"Could not record lock details in {self.path}: {exc}") from exc

    def _write_metadata(self, slug: str) -> None:
        metadata = {
            "audit_slug": slug,
            "started_at": _utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "process_id": os.getpid(),
            "hostname": socket.gethostname(),
            "signalscope_version": SIGNALSCOPE_VERSION,
        }
        os.ftruncate(self._fd, 0)
        os.lseek(self._fd, 0, os.SEEK_SET)
        os.write(self._fd, (json.dumps(metadata) + "\n").encode("utf-8"))

    def release(self) -> None:
        if self._fd is None:
            return
        fd, self._fd = self._fd, None
        try:
            _os_unlock(fd)
        finally:
            os.close(fd)

    def __enter__(self) -> AuditLock:
        return self

    def __exit__(self, *exc_info) -> None:
        self.release()


def probe_lock(path: str | Path) -> bool:
    """Whether another process currently holds the lock at path. Never
    creates the file and never changes it; a missing file is not held.
    Raises MonitoringLockError if the lock state cannot be determined."""
    path = Path(path)
    if not path.exists():
        return False
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    except OSError as exc:
        raise MonitoringLockError(f"Could not open {path}: {exc}") from exc
    try:
        try:
            _try_lock(fd, path)
        except MonitoringLockHeld:
            return True
        _os_unlock(fd)
        return False
    finally:
        os.close(fd)


# --------------------------------------------------------------------------
# Executing one cycle
# --------------------------------------------------------------------------

CHUNK_SIZE = 5  # questions attempted per structured-batch call (the spend breaker's unit)

OUTCOME_COMPLETED = "completed"
OUTCOME_INCOMPLETE = "incomplete"

# Gemini API failures as the released modules report them: an answer call
# (gemini_client.generate_response) or an analysis call
# (response_analyzer.analyze_response). Only these are classified with
# run_batch_audit.is_retryable_error - never a malformed-analysis message,
# whose embedded model output could contain e.g. "500".
_API_FAILURE_PREFIXES = ("Gemini API call failed:", "Gemini analysis call failed:")


def is_retryable_failure(message: str) -> bool:
    """Whether a question failure recorded by the structured batch is a
    temporary Gemini API failure (429/5xx) by the batch's own rule."""
    return message.startswith(_API_FAILURE_PREFIXES) and is_retryable_error(Exception(message))


@dataclass(frozen=True)
class CycleResult:
    """What one monitoring cycle did."""

    audit_slug: str
    outcome: str
    exit_code: int
    plan: CyclePlan | None = None
    actions_taken: tuple[str, ...] = ()
    final_state: str | None = None
    new_snapshot: str | None = None
    reasons: tuple[str, ...] = ()
    comparison_path: Path | None = None


@dataclass(frozen=True)
class _Progress:
    not_started: int
    answer_stored: int
    complete: int
    integrity: int

    @property
    def actionable(self) -> int:
        return self.not_started + self.answer_stored


def _progress(slug: str, audits_dir) -> _Progress:
    active = inspect_active_run(slug, audits_dir=audits_dir)
    codes = [s.state for s in active.states]
    return _Progress(
        not_started=codes.count(STATE_NOT_STARTED),
        answer_stored=codes.count(STATE_ANSWER_STORED),
        complete=active.structurally_complete_count,
        integrity=codes.count(STATE_EVIDENCE_INTEGRITY_ERROR),
    )


def _collect(
    slug: str,
    audits_dir,
    *,
    chunk_size: int,
    request_delay_seconds: float,
    sleep_fn: Callable[[float], None],
    today: Callable[[], date],
    actions: list[str],
) -> tuple[str, str] | None:
    """Collect the current run in chunks with the released structured batch.
    Returns None when no actionable question is left, or (outcome, reason)
    when collection had to stop."""
    audit_dir = (_audits_root(audits_dir) / slug).resolve()
    questions_path, results_path = audit_dir / QUESTIONS_FILENAME, audit_dir / RESULTS_FILENAME
    config = inspect_active_run(slug, audits_dir=audits_dir).config
    before = _progress(slug, audits_dir)
    for chunk in range(1, 2 * before.actionable + 2):  # each productive chunk moves a question on
        if before.actionable == 0:
            return None
        if chunk > 1:
            sleep_fn(request_delay_seconds)
        try:
            result = run_structured_batch_audit(
                str(questions_path),
                str(results_path),
                request_delay_seconds,
                chunk_size,
                sleep_fn=sleep_fn,
                audit_config=config,
                today=today,
            )
        except (AuditRunnerError, WriteAuditResultError, StructuredBatchError) as exc:
            return OUTCOME_OPERATOR_ACTION, f"The structured batch could not start: {exc}"
        actions.append(f"collected chunk {chunk} ({len(result.completed)} completed, {len(result.failed)} failed)")
        if result.stopped or result.integrity_problems:
            detail = result.stopped or "; ".join(f"{q}: {d}" for q, d in result.integrity_problems)
            return OUTCOME_OPERATOR_ACTION, f"Collection stopped on a storage or integrity problem: {detail}"
        after = _progress(slug, audits_dir)
        if after.integrity:
            return OUTCOME_OPERATOR_ACTION, "Evidence integrity problems appeared during collection."
        progressed = after.complete > before.complete or after.not_started < before.not_started
        if not progressed:
            failures = "; ".join(f"{q}: {message}" for q, message in result.failed) or "no question progressed"
            if result.failed and all(is_retryable_failure(message) for _, message in result.failed):
                return OUTCOME_INCOMPLETE, (
                    f"Collection paused after a chunk made no progress because of temporary Gemini failures "
                    f"({failures}); the next trigger resumes it."
                )
            return OUTCOME_OPERATOR_ACTION, f"Collection stopped: a chunk made no progress ({failures})."
        before = after
    return OUTCOME_OPERATOR_ACTION, "Collection did not converge; stopped as a precaution."


def run_monitoring_cycle(
    slug: str,
    interval_days: int,
    *,
    audits_dir: str | Path | None = None,
    reports_dir: str | Path | None = None,
    now: Callable[[], datetime] | None = None,
    api_key_present: Callable[[], bool] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    request_delay_seconds: float = DEFAULT_REQUEST_DELAY_SECONDS,
    today: Callable[[], date] = date.today,
    chunk_size: int = CHUNK_SIZE,
) -> CycleResult:
    """Run at most one monitoring cycle for an audit, holding its lock
    throughout and acting only on a plan made while holding it.

    Reuses start_new_run (new cycle or interrupted-reset recovery), the
    structured batch (in chunks of chunk_size, stopping when a chunk makes
    no progress), create_snapshot (complete runs only) and
    compare_snapshots (previous -> latest, when that comparison is expected
    and missing). Never retries a whole cycle; a snapshot is never rolled
    back because its comparison failed.
    """
    path = lock_path(slug, audits_dir=audits_dir)
    if not path.parent.is_dir():
        plan = plan_cycle(slug, interval_days, audits_dir=audits_dir, reports_dir=reports_dir, now=now,
                          api_key_present=api_key_present)
        return CycleResult(slug, plan.outcome, plan.exit_code, plan, reasons=plan.reasons)
    lock = AuditLock(path)
    try:
        lock.acquire(slug)
    except MonitoringLockHeld as exc:
        return CycleResult(slug, OUTCOME_ALREADY_RUNNING, EXIT_ALREADY_RUNNING, reasons=(str(exc),))
    except MonitoringLockError as exc:
        return CycleResult(slug, OUTCOME_OPERATOR_ACTION, EXIT_OPERATOR_ACTION, reasons=(str(exc),))
    try:
        return _execute(
            slug, interval_days, audits_dir=audits_dir, reports_dir=reports_dir, now=now,
            api_key_present=api_key_present, sleep_fn=sleep_fn, request_delay_seconds=request_delay_seconds,
            today=today, chunk_size=chunk_size,
        )
    finally:
        lock.release()


def _execute(slug, interval_days, *, audits_dir, reports_dir, now, api_key_present, sleep_fn,
             request_delay_seconds, today, chunk_size) -> CycleResult:
    def replan() -> CyclePlan:
        return plan_cycle(slug, interval_days, audits_dir=audits_dir, reports_dir=reports_dir, now=now,
                          api_key_present=api_key_present)

    first = plan = replan()
    actions: list[str] = []

    def finish(outcome: str, exit_code: int, *reasons: str, new_snapshot: str | None = None,
               comparison: Path | None = None) -> CycleResult:
        try:
            final = active_run_state(slug, audits_dir=audits_dir).state
        except AuditHistoryError:
            final = None
        return CycleResult(slug, outcome, exit_code, first, tuple(actions), final, new_snapshot, reasons, comparison)

    def compare(target: CyclePlan, new_snapshot: str | None = None) -> CycleResult:
        earlier, later = target.previous_snapshot, target.latest_snapshot
        try:
            comparison = compare_snapshots(slug, earlier, later, audits_dir=audits_dir, reports_dir=reports_dir,
                                           generated_at=today())
        except (AuditHistoryError, OSError) as exc:
            return finish(OUTCOME_OPERATOR_ACTION, EXIT_OPERATOR_ACTION,
                          f"The comparison {earlier} -> {later} was refused or failed: {exc}",
                          new_snapshot=new_snapshot)
        expected = comparison_output_path(slug, earlier, later, reports_dir=_reports_root(reports_dir, audits_dir))
        if comparison.output_path != expected or not expected.is_file():
            return finish(OUTCOME_OPERATOR_ACTION, EXIT_OPERATOR_ACTION,
                          f"The comparison report {expected} was not produced.", new_snapshot=new_snapshot)
        actions.append(f"comparison {earlier} -> {later} created")
        if replan().steps == (STEP_COMPARE,):
            return finish(OUTCOME_OPERATOR_ACTION, EXIT_OPERATOR_ACTION,
                          "The comparison is still reported as missing after it was written.",
                          new_snapshot=new_snapshot, comparison=expected)
        return finish(OUTCOME_COMPLETED, EXIT_OK, f"Comparison {earlier} -> {later} written to {expected}.",
                      new_snapshot=new_snapshot, comparison=expected)

    if plan.outcome != OUTCOME_READY:
        return finish(plan.outcome, plan.exit_code, *plan.reasons)
    if plan.steps == (STEP_COMPARE,):
        return compare(plan)

    if STEP_NEW_RUN in plan.steps or STEP_RECOVER_NEW_RUN in plan.steps:
        try:
            reset = start_new_run(slug, audits_dir=audits_dir)
        except AuditHistoryError as exc:
            return finish(OUTCOME_OPERATOR_ACTION, EXIT_OPERATOR_ACTION, f"new-run was refused: {exc}")
        actions.append(
            ("finished interrupted new-run" if reset.recovered else "new-run")
            + f" (previous run preserved in snapshot {reset.preserved_run_id})"
        )
        plan = replan()
        if plan.outcome != OUTCOME_READY or STEP_COLLECT not in plan.steps:
            return finish(plan.outcome if plan.outcome != OUTCOME_READY else OUTCOME_OPERATOR_ACTION,
                          EXIT_OPERATOR_ACTION, "After new-run the cycle could not continue.", *plan.reasons)

    if STEP_COLLECT in plan.steps:
        stopped = _collect(slug, audits_dir, chunk_size=chunk_size, request_delay_seconds=request_delay_seconds,
                           sleep_fn=sleep_fn, today=today, actions=actions)
        if stopped is not None:
            outcome, reason = stopped
            code = EXIT_INCOMPLETE if outcome == OUTCOME_INCOMPLETE else EXIT_OPERATOR_ACTION
            return finish(outcome, code, reason)
        progress = _progress(slug, audits_dir)
        if progress.integrity:
            return finish(OUTCOME_OPERATOR_ACTION, EXIT_OPERATOR_ACTION,
                          "Evidence integrity problems must be investigated by the operator.")
        if not inspect_active_run(slug, audits_dir=audits_dir).is_complete:
            return finish(
                OUTCOME_OPERATOR_ACTION,
                EXIT_OPERATOR_ACTION,
                f"Collection finished with {progress.complete} question(s) structurally complete and nothing "
                "left to collect automatically.",
                _ALLOW_PARTIAL_NOTE.format(slug=slug),
            )

    try:
        snapshot = create_snapshot(slug, audits_dir=audits_dir, allow_partial=False, now=now)
    except AuditHistoryError as exc:
        return finish(OUTCOME_OPERATOR_ACTION, EXIT_OPERATOR_ACTION, f"The complete run could not be snapshotted: {exc}")
    actions.append(f"snapshot {snapshot.run_id} created")
    after = replan()
    if after.outcome == OUTCOME_READY and after.steps == (STEP_COMPARE,):
        return compare(after, new_snapshot=snapshot.run_id)
    if after.outcome == OUTCOME_NOT_DUE:
        return finish(OUTCOME_COMPLETED, EXIT_OK, f"Snapshot {snapshot.run_id} preserves the completed run.",
                      *after.reasons, new_snapshot=snapshot.run_id)
    return finish(OUTCOME_OPERATOR_ACTION, EXIT_OPERATOR_ACTION,
                  f"Snapshot {snapshot.run_id} was created, but the cycle could not continue.", *after.reasons,
                  new_snapshot=snapshot.run_id)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _positive_days(value: str) -> int:
    try:
        days = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"must be a positive whole number of days, got {value!r}") from None
    if days < 1:
        raise argparse.ArgumentTypeError(f"must be a positive whole number of days, got {value!r}")
    return days


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run (or, with --dry-run, plan) one monitoring cycle for an audit.")
    parser.add_argument("--audit", required=True, help="Audit slug under audits/")
    parser.add_argument(
        "--interval-days",
        required=True,
        type=_positive_days,
        help="Start a new cycle only when the latest snapshot is at least this many days old",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Report the planned actions without calling Gemini or changing files"
    )
    return parser.parse_args(argv)


def _run_summary(result: CycleResult) -> str:
    plan = result.plan
    return json.dumps({
        "audit_slug": result.audit_slug,
        "mode": "run",
        "outcome": result.outcome,
        "action": plan.action if plan else "none",
        "active_state": plan.active_state if plan else None,
        "final_state": result.final_state,
        "latest_snapshot": plan.latest_snapshot if plan else None,
        "new_snapshot": result.new_snapshot,
        "comparison": str(result.comparison_path) if result.comparison_path else None,
        "requires_collection": plan.requires_collection if plan else False,
        "exit_code": result.exit_code,
    }, ensure_ascii=False)


def _run(args: argparse.Namespace) -> int:
    try:
        result = run_monitoring_cycle(args.audit, args.interval_days)
    except (MonitoringError, AuditHistoryError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        result = CycleResult(args.audit, OUTCOME_OPERATOR_ACTION, EXIT_OPERATOR_ACTION)
        print(_run_summary(result))
        return result.exit_code
    print()
    print(f"Monitoring cycle for {result.audit_slug}")
    if result.plan is not None:
        print(f"Planned actions: {result.plan.action}")
    for action in result.actions_taken:
        print(f"  done: {action}")
    for reason in result.reasons:
        print(f"  {reason}")
    if result.new_snapshot:
        print(f"New snapshot: {result.new_snapshot}")
    if result.comparison_path:
        print(f"Comparison: {result.comparison_path}")
    print(f"Outcome: {result.outcome} (exit code {result.exit_code})")
    print(_run_summary(result))
    return result.exit_code


def _summary(plan: CyclePlan | None, slug: str, *, outcome: str, exit_code: int, lock_held: bool | None) -> str:
    return json.dumps({
        "audit_slug": slug,
        "mode": "dry-run",
        "outcome": outcome,
        "action": plan.action if plan else "none",
        "active_state": plan.active_state if plan else None,
        "due": plan.due if plan else None,
        "requires_collection": plan.requires_collection if plan else False,
        "latest_snapshot": plan.latest_snapshot if plan else None,
        "previous_snapshot": plan.previous_snapshot if plan else None,
        "lock_held": lock_held,
        "exit_code": exit_code,
    }, ensure_ascii=False)


def _print_plan(plan: CyclePlan, lock_held: bool) -> None:
    print(f"Audit: {plan.audit_slug}")
    print(f"Current run: {plan.active_state or 'unknown'}")
    print(f"Evidence integrity problems: {plan.integrity_problems}")
    print(f"Latest snapshot: {plan.latest_snapshot or 'none'}")
    if plan.previous_snapshot:
        print(f"Previous snapshot: {plan.previous_snapshot}")
    if plan.due is not None:
        print(f"Due (interval {plan.interval_days} day(s)): {'yes' if plan.due else 'no'}")
    if plan.methodology_differences:
        print("Methodology differences from the latest snapshot:")
        for difference in plan.methodology_differences:
            print(f"  - {difference}")
    else:
        print("Methodology: no differences found" if plan.active_state else "Methodology: not checked")
    print(f"Collection required: {'yes' if plan.requires_collection else 'no'}")
    if plan.requires_api_key:
        print(f"Gemini API key: {'configured' if plan.api_key_present else 'NOT configured'}")
    print(f"Monitoring lock held by another process: {'yes' if lock_held else 'no'}")
    print(f"Planned actions: {plan.action}")
    for reason in plan.reasons:
        print(f"  {reason}")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = parse_args(argv)
    if not args.dry_run:
        return _run(args)

    try:
        plan = plan_cycle(args.audit, args.interval_days)
        lock_held = probe_lock(lock_path(args.audit))
    except (MonitoringError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        print(_summary(None, args.audit, outcome=OUTCOME_OPERATOR_ACTION,
                       exit_code=EXIT_OPERATOR_ACTION, lock_held=None))
        return EXIT_OPERATOR_ACTION

    print("DRY RUN - no Gemini call, no file change.")
    _print_plan(plan, lock_held)
    outcome, exit_code = (
        (OUTCOME_ALREADY_RUNNING, EXIT_ALREADY_RUNNING) if lock_held else (plan.outcome, plan.exit_code)
    )
    print(f"Outcome: {outcome} (exit code {exit_code})")
    print(_summary(plan, args.audit, outcome=outcome, exit_code=exit_code, lock_held=lock_held))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

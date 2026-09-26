"""Structured batch evidence collection for SignalScope AI (v2.3).

Collects complete structured audit evidence for an audit's buyer
questions, one question at a time. Each new Gemini answer is first
preserved in full as a raw evidence file:

    audits/<slug>/raw_responses/<question_id>__gemini.json

and is then analysed from that stored file with the existing
response_analyzer, producing a row in the existing 11-column
audit_results.csv format. Because analysis always reads the stored
answer, a question whose answer was saved but not yet analysed is
resumed without asking Gemini again.

The batch classifies every question first (states A-F, see
classify_question), then works through the questions still needing work
(A: not started, B: answer stored) in buyer_questions.csv order, saving
each completed row to audit_results.csv before moving on. Completed,
legacy and problem questions are never re-asked or rewritten.

    python src/run_structured_batch_audit.py --audit <slug> [--limit N] [--delay S]

Reuses, unchanged: run_batch_audit.generate_with_retry (answer retries),
response_analyzer.analyze_response (structural analysis),
run_structured_audit.build_structured_row (row construction) and the
write_single_audit_result schema and snippet rules.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

import gemini_client
from audit_config import AuditConfig, AuditConfigError, default_audit_config, load_audit_config
from audit_runner import AuditRunnerError, load_questions
from gemini_client import GeminiClientError
from response_analyzer import VALID_BRAND_CITED, VALID_SENTIMENTS, ResponseAnalysisError, analyze_response
from run_batch_audit import (
    DEFAULT_REQUEST_DELAY_SECONDS,
    MAX_ATTEMPTS,
    RETRY_DELAYS_SECONDS,
    generate_with_retry,
    is_retryable_error,
)
from run_structured_audit import TARGET_ENGINE, build_structured_row
from write_single_audit_result import (
    RESULTS_SCHEMA,
    WriteAuditResultError,
    check_for_duplicate,
    load_existing_results,
    normalise_snippet,
    write_results_atomically,
)

EVIDENCE_DIRNAME = "raw_responses"
EVIDENCE_FORMAT_VERSION = 1
EVIDENCE_FIELDS = (
    "format_version",
    "audit_slug",
    "question_id",
    "question",
    "engine",
    "requested_model",
    "run_date",
    "raw_response_text",
)

QUESTION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_POSITION_PATTERN = re.compile(r"^[1-9][0-9]*$")

# Question states (see classify_question).
STATE_NOT_STARTED = "A"
STATE_ANSWER_STORED = "B"
STATE_COMPLETE_WITH_EVIDENCE = "C"
STATE_LEGACY_INCOMPLETE = "D"
STATE_LEGACY_COMPLETE_NO_EVIDENCE = "E"
STATE_EVIDENCE_INTEGRITY_ERROR = "F"
ACTIONABLE_STATES = {STATE_NOT_STARTED, STATE_ANSWER_STORED}


class StructuredBatchError(Exception):
    """Base class for structured batch evidence-collection errors."""


class EvidenceIntegrityError(StructuredBatchError):
    """A raw evidence file is malformed, conflicts with the audit, or
    already exists where a new one would be published. Never resolved by
    overwriting."""


class EvidenceStorageError(StructuredBatchError):
    """A raw evidence file could not be published safely."""


class QuestionProcessingError(StructuredBatchError):
    """A question cannot be processed, or its generated row is invalid."""


# --------------------------------------------------------------------------
# Question IDs
# --------------------------------------------------------------------------


def validate_question_ids(question_rows: list[dict[str, str]]) -> None:
    """Question IDs are used in evidence file names: each must match
    QUESTION_ID_PATTERN, and no two may differ only by case (which would
    be the same file on a case-insensitive filesystem). Raises
    QuestionProcessingError listing every problem."""
    problems: list[str] = []
    seen: dict[str, str] = {}
    for row in question_rows:
        question_id = row.get("question_id")
        if not isinstance(question_id, str) or not QUESTION_ID_PATTERN.fullmatch(question_id):
            problems.append(f"{question_id!r} is not a safe question ID (letters, digits, '_' and '-' only)")
            continue
        key = question_id.casefold()
        if key in seen and seen[key] != question_id:
            problems.append(f"{seen[key]!r} and {question_id!r} differ only by case")
        seen.setdefault(key, question_id)
    if problems:
        raise QuestionProcessingError("Invalid question IDs: " + "; ".join(problems))


def evidence_dir_for(results_csv_path: str | Path) -> Path:
    """The raw evidence folder for an audit: raw_responses/ beside its
    audit_results.csv."""
    return Path(results_csv_path).parent / EVIDENCE_DIRNAME


def evidence_path(evidence_dir: str | Path, question_id: str) -> Path:
    validate_question_ids([{"question_id": question_id}])
    return Path(evidence_dir) / f"{question_id}__{TARGET_ENGINE.lower()}.json"


# --------------------------------------------------------------------------
# Raw evidence
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class RawEvidence:
    """The complete answer Gemini gave to one question, with the facts
    needed to trace it. requested_model is the model SignalScope asked
    for (gemini_client.DEFAULT_MODEL), not a confirmed served version."""

    format_version: int
    audit_slug: str
    question_id: str
    question: str
    engine: str
    requested_model: str
    run_date: str
    raw_response_text: str


def _check_evidence_fields() -> None:
    """Module integrity check (not an assert, so it also runs under
    python -O): the evidence file format and RawEvidence must agree."""
    actual = tuple(field.name for field in dataclasses.fields(RawEvidence))
    if actual != EVIDENCE_FIELDS:
        raise RuntimeError(f"RawEvidence fields {actual} do not match EVIDENCE_FIELDS {EVIDENCE_FIELDS}")


_check_evidence_fields()


def serialise_evidence(evidence: RawEvidence) -> str:
    """Deterministic evidence JSON: fields in EVIDENCE_FIELDS order,
    indent=2, UTF-8 characters kept as-is, trailing newline."""
    return json.dumps(dataclasses.asdict(evidence), indent=2, ensure_ascii=False) + "\n"


def _is_iso_date(value: object) -> bool:
    if not isinstance(value, str) or not _ISO_DATE_PATTERN.fullmatch(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def parse_evidence(text: str, *, audit_slug: str, question_row: dict[str, str], source: str = "evidence") -> RawEvidence:
    """Parse and validate evidence JSON against the current audit and
    question. Raises EvidenceIntegrityError. A requested_model that
    differs from today's default is accepted: it records what was asked
    for when the answer was collected."""

    def fail(reason: str) -> EvidenceIntegrityError:
        return EvidenceIntegrityError(f"Invalid raw evidence {source}: {reason}")

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise fail(f"not valid JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise fail("not a JSON object")

    missing = set(EVIDENCE_FIELDS) - set(data)
    unexpected = set(data) - set(EVIDENCE_FIELDS)
    if missing:
        raise fail(f"missing field(s) {sorted(missing)}")
    if unexpected:
        raise fail(f"unexpected field(s) {sorted(unexpected)}")

    version = data["format_version"]
    if isinstance(version, bool) or not isinstance(version, int) or version != EVIDENCE_FORMAT_VERSION:
        raise fail(f"unsupported format_version {version!r}")
    for field in EVIDENCE_FIELDS[1:]:
        if not isinstance(data[field], str):
            raise fail(f"{field} must be a string")

    if data["audit_slug"] != audit_slug:
        raise fail(f"audit_slug {data['audit_slug']!r} does not match audit {audit_slug!r}")
    if data["question_id"] != question_row["question_id"]:
        raise fail(f"question_id {data['question_id']!r} does not match {question_row['question_id']!r}")
    if data["question"] != question_row["question"]:
        raise fail(f"question text does not match buyer_questions.csv for {question_row['question_id']!r}")
    if data["engine"] != TARGET_ENGINE:
        raise fail(f"engine {data['engine']!r} is not {TARGET_ENGINE!r}")
    if not data["requested_model"].strip():
        raise fail("requested_model is empty")
    if not _is_iso_date(data["run_date"]):
        raise fail(f"run_date {data['run_date']!r} is not a YYYY-MM-DD date")
    if not data["raw_response_text"].strip():
        raise fail("raw_response_text is empty")

    return RawEvidence(**data)


def load_evidence(path: Path, *, audit_slug: str, question_row: dict[str, str]) -> RawEvidence | None:
    """Load and validate an evidence file, or return None if there is
    none. Raises EvidenceIntegrityError for an unreadable or invalid file."""
    if not path.exists():
        return None
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise EvidenceIntegrityError(f"Invalid raw evidence {path}: cannot be read as UTF-8 ({exc})") from exc
    return parse_evidence(text, audit_slug=audit_slug, question_row=question_row, source=str(path))


def publish_evidence(evidence: RawEvidence, evidence_dir: str | Path) -> Path:
    """Atomically publish an evidence file without ever replacing one.

    Writes a temporary file in the evidence folder (flushed and fsynced),
    then hard-links it to the final name - which fails if that name
    already exists - and removes the temporary file. Raises
    EvidenceIntegrityError if the evidence file already exists (it is
    left untouched), or EvidenceStorageError if it cannot be written or
    the filesystem does not support hard links. There is no fallback that
    could overwrite existing evidence.
    """
    final = evidence_path(evidence_dir, evidence.question_id)
    final.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{final.name}.", suffix=".tmp", dir=str(final.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(serialise_evidence(evidence))
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(tmp_name, final)
        except FileExistsError as exc:
            raise EvidenceIntegrityError(
                f"Raw evidence already exists and will not be overwritten: {final}"
            ) from exc
        except (OSError, NotImplementedError) as exc:
            raise EvidenceStorageError(
                f"Could not publish raw evidence {final} (a filesystem supporting hard links is required): {exc}"
            ) from exc
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
    return final


# --------------------------------------------------------------------------
# Structural completeness
# --------------------------------------------------------------------------


def structural_problems(row: dict[str, str], question_row: dict[str, str]) -> list[str]:
    """Reasons a Gemini result row is not structurally complete for its
    question (empty list if it is). competitors_cited and sources_cited
    may legitimately be empty."""
    if list(row) != RESULTS_SCHEMA:
        return [f"columns are not the results schema: {list(row)}"]
    problems: list[str] = []
    if row["engine"] != TARGET_ENGINE:
        problems.append(f"engine is {row['engine']!r}")
    for field, source_field in (
        ("question_id", "question_id"),
        ("question", "question"),
        ("funnel_stage", "buyer_journey_stage"),
    ):
        if row[field] != question_row[source_field]:
            problems.append(f"{field} does not match the question file")
    if not _is_iso_date(row["run_date"]):
        problems.append(f"run_date {row['run_date']!r} is not a YYYY-MM-DD date")
    if not (row["answer_snippet"] or "").strip():
        problems.append("answer_snippet is empty")
    if row["brand_cited"] not in VALID_BRAND_CITED:
        problems.append(f"brand_cited {row['brand_cited']!r} is not Y or N")
    if row["sentiment"] not in VALID_SENTIMENTS:
        problems.append(f"sentiment {row['sentiment']!r} is not one of {sorted(VALID_SENTIMENTS)}")
    position = row["brand_position"]
    if position != "" and not _POSITION_PATTERN.fullmatch(position or ""):
        problems.append(f"brand_position {position!r} is not empty or a whole number >= 1")
    elif position != "" and row["brand_cited"] == "N":
        problems.append("brand_position is set although brand_cited is N")
    for field in RESULTS_SCHEMA:
        value = row[field]
        if not isinstance(value, str):
            problems.append(f"{field} is not text")
        elif "\n" in value or "\r" in value:
            problems.append(f"{field} contains a line break")
    return problems


def is_structurally_complete(row: dict[str, str], question_row: dict[str, str]) -> bool:
    return not structural_problems(row, question_row)


# --------------------------------------------------------------------------
# Question states
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class QuestionState:
    state: str
    question_id: str
    evidence: RawEvidence | None
    row: dict[str, str] | None
    detail: str


def _gemini_rows(existing_rows: list[dict[str, str]], question_id: str) -> list[dict[str, str]]:
    return [r for r in existing_rows if r.get("question_id") == question_id and r.get("engine") == TARGET_ENGINE]


def classify_question(
    question_row: dict[str, str],
    existing_rows: list[dict[str, str]],
    *,
    evidence_dir: str | Path,
    audit_slug: str,
) -> QuestionState:
    """Classify one question from its existing Gemini result row (if any)
    and its raw evidence file (if any). Reads only; never writes.

      A  no Gemini row, no evidence            -> answer, then analyse
      B  no Gemini row, valid evidence         -> analyse stored answer
      C  complete row + matching evidence      -> done
      D  incomplete Gemini row (any evidence)  -> legacy; never reprocessed
      E  complete row, no evidence             -> legacy complete; kept as is
      F  invalid/conflicting evidence, or a complete row that disagrees
         with its evidence, or duplicate Gemini rows -> integrity error
    """
    question_id = question_row["question_id"]
    path = evidence_path(evidence_dir, question_id)
    rows = _gemini_rows(existing_rows, question_id)
    if len(rows) > 1:
        return QuestionState(STATE_EVIDENCE_INTEGRITY_ERROR, question_id, None, None,
                             f"{len(rows)} Gemini result rows exist for {question_id}")
    row = rows[0] if rows else None

    if row is not None and not is_structurally_complete(row, question_row):
        note = "; a raw evidence file also exists" if path.exists() else ""
        return QuestionState(STATE_LEGACY_INCOMPLETE, question_id, None, row,
                             f"structurally incomplete Gemini row, not reprocessed{note}")

    try:
        evidence = load_evidence(path, audit_slug=audit_slug, question_row=question_row)
    except EvidenceIntegrityError as exc:
        return QuestionState(STATE_EVIDENCE_INTEGRITY_ERROR, question_id, None, row, str(exc))

    if row is None:
        if evidence is None:
            return QuestionState(STATE_NOT_STARTED, question_id, None, None, "not started")
        return QuestionState(STATE_ANSWER_STORED, question_id, evidence, None, "answer stored, not yet analysed")

    if evidence is None:
        return QuestionState(STATE_LEGACY_COMPLETE_NO_EVIDENCE, question_id, None, row,
                             "structurally complete row without a stored full answer")
    if row["answer_snippet"] != normalise_snippet(evidence.raw_response_text):
        return QuestionState(STATE_EVIDENCE_INTEGRITY_ERROR, question_id, evidence, row,
                             f"answer_snippet in audit_results.csv does not match the stored answer for {question_id}")
    if row["run_date"] != evidence.run_date:
        return QuestionState(STATE_EVIDENCE_INTEGRITY_ERROR, question_id, evidence, row,
                             f"run_date in audit_results.csv does not match the stored answer for {question_id}")
    return QuestionState(STATE_COMPLETE_WITH_EVIDENCE, question_id, evidence, row, "complete")


# --------------------------------------------------------------------------
# Single-question processing
# --------------------------------------------------------------------------


def analyze_with_retry(
    response_text: str,
    brand: str,
    known_competitors: list[str],
    question_id: str,
    max_attempts: int = MAX_ATTEMPTS,
    retry_delays: list[float] = RETRY_DELAYS_SECONDS,
    sleep_fn=time.sleep,
) -> dict:
    """Call analyze_response, retrying with the same policy as the answer
    call (generate_with_retry) - but only when the failure was caused by a
    retryable Gemini API error. Malformed or invalid analysis output is
    never retried, even if its text happens to contain e.g. "500"."""
    for attempt in range(1, max_attempts + 1):
        try:
            return analyze_response(response_text, brand, known_competitors)
        except ResponseAnalysisError as exc:
            cause = exc.__cause__
            retryable = isinstance(cause, GeminiClientError) and is_retryable_error(cause)
            if not retryable or attempt >= max_attempts:
                raise
            delay = retry_delays[min(attempt - 1, len(retry_delays) - 1)]
            print(
                f"  [{question_id}] temporary analysis error on attempt {attempt}/{max_attempts}, "
                f"retrying in {delay}s: {cause}"
            )
            sleep_fn(delay)
    raise AssertionError("unreachable")  # pragma: no cover


def process_question(
    question_row: dict[str, str],
    config: AuditConfig,
    existing_rows: list[dict[str, str]],
    *,
    evidence_dir: str | Path,
    sleep_fn=time.sleep,
    today: Callable[[], date] = date.today,
) -> dict[str, str]:
    """Produce one structurally complete result row for a question in
    state A or B. Does not write audit_results.csv.

    State A: ask Gemini (generate_with_retry), publish the full answer as
    raw evidence, then continue as state B.
    State B: reload and validate the stored evidence, analyse exactly that
    stored answer (analyze_with_retry), build the row with
    build_structured_row, take run_date from the evidence, and check the
    row is structurally complete and matches the evidence.

    Raises QuestionProcessingError for an unsafe question ID, a question
    not in state A or B, or an invalid row; GeminiClientError if the
    answer call fails; ResponseAnalysisError if analysis fails;
    EvidenceIntegrityError / EvidenceStorageError for evidence problems.
    Any evidence published before a later failure is kept, so the next
    attempt resumes from state B without asking Gemini again.
    """
    validate_question_ids([question_row])
    question_id = question_row["question_id"]
    state = classify_question(question_row, existing_rows, evidence_dir=evidence_dir, audit_slug=config.slug)
    if state.state not in ACTIONABLE_STATES:
        raise QuestionProcessingError(f"{question_id} is in state {state.state} ({state.detail}); not processed")

    path = evidence_path(evidence_dir, question_id)
    if state.state == STATE_NOT_STARTED:
        answer = generate_with_retry(question_row["question"], question_id, sleep_fn=sleep_fn)
        if not answer or not answer.strip():
            raise GeminiClientError("Gemini API returned an empty response.")
        publish_evidence(
            RawEvidence(
                format_version=EVIDENCE_FORMAT_VERSION,
                audit_slug=config.slug,
                question_id=question_id,
                question=question_row["question"],
                engine=TARGET_ENGINE,
                requested_model=gemini_client.DEFAULT_MODEL,
                run_date=today().isoformat(),
                raw_response_text=answer,
            ),
            evidence_dir,
        )

    # State B - also reached straight after publishing, so new and resumed
    # questions are analysed from exactly what was stored.
    evidence = load_evidence(path, audit_slug=config.slug, question_row=question_row)
    if evidence is None:
        raise EvidenceIntegrityError(f"Raw evidence for {question_id} is missing: {path}")

    analysis = analyze_with_retry(
        evidence.raw_response_text, config.brand, list(config.competitors), question_id, sleep_fn=sleep_fn
    )
    row = build_structured_row(question_row, evidence.raw_response_text, analysis)
    row["run_date"] = evidence.run_date

    problems = structural_problems(row, question_row)
    if problems:
        raise QuestionProcessingError(f"{question_id} produced an incomplete row: {'; '.join(problems)}")
    if row["answer_snippet"] != normalise_snippet(evidence.raw_response_text):
        raise QuestionProcessingError(f"{question_id} row snippet does not match the stored answer")
    return row


# --------------------------------------------------------------------------
# Batch
# --------------------------------------------------------------------------

STATE_LABELS = {
    STATE_COMPLETE_WITH_EVIDENCE: "complete with evidence",
    STATE_ANSWER_STORED: "answer stored, not yet analysed",
    STATE_NOT_STARTED: "not started",
    STATE_LEGACY_INCOMPLETE: "legacy incomplete",
    STATE_LEGACY_COMPLETE_NO_EVIDENCE: "complete, no stored full answer",
    STATE_EVIDENCE_INTEGRITY_ERROR: "evidence integrity problem",
}

# Failures that leave durable state consistent: the question is recorded
# as failed and the batch continues.
_QUESTION_FAILURES = (GeminiClientError, ResponseAnalysisError, QuestionProcessingError)
# Failures that make durable state uncertain: the batch stops.
_STORAGE_FAILURES = (EvidenceStorageError, EvidenceIntegrityError, WriteAuditResultError, OSError)


@dataclass
class StructuredBatchResult:
    """What a structured batch run found and did."""

    total_questions: int = 0
    initial_states: dict[str, list[str]] = dataclasses.field(default_factory=dict)
    attempted: list[str] = dataclasses.field(default_factory=list)
    completed_new_answers: list[str] = dataclasses.field(default_factory=list)
    completed_from_stored: list[str] = dataclasses.field(default_factory=list)
    failed: list[tuple[str, str]] = dataclasses.field(default_factory=list)
    integrity_problems: list[tuple[str, str]] = dataclasses.field(default_factory=list)
    stopped: str | None = None
    pending_after: int = 0

    @property
    def completed(self) -> list[str]:
        return self.completed_new_answers + self.completed_from_stored

    def ids_in(self, state: str) -> list[str]:
        return self.initial_states.get(state, [])

    @property
    def exit_code(self) -> int:
        return 1 if (self.failed or self.integrity_problems or self.stopped) else 0


def _duplicate_gemini_rows(rows: list[dict[str, str]]) -> list[str]:
    counts: dict[str, int] = {}
    for row in rows:
        if row.get("engine") == TARGET_ENGINE:
            counts[row.get("question_id", "")] = counts.get(row.get("question_id", ""), 0) + 1
    return sorted(question_id for question_id, count in counts.items() if count > 1)


def _persist_row(results_csv_path: str, rows: list[dict[str, str]], row: dict[str, str]) -> list[dict[str, str]]:
    """Save one row. The file on disk must still be exactly what this run
    last saw; the existing duplicate check then guards (question_id,
    engine). Returns the new row list. Raises StructuredBatchError or
    WriteAuditResultError if the file changed or a duplicate would be
    created, OSError if the write fails."""
    on_disk = load_existing_results(results_csv_path)
    if on_disk != rows:
        raise StructuredBatchError(
            f"{results_csv_path} changed during the run (another process may be writing to it); stopping."
        )
    check_for_duplicate(on_disk, row["question_id"], TARGET_ENGINE)
    new_rows = on_disk + [row]
    write_results_atomically(results_csv_path, new_rows)
    return new_rows


def run_structured_batch_audit(
    question_csv_path: str | None = None,
    results_csv_path: str | None = None,
    request_delay_seconds: float = DEFAULT_REQUEST_DELAY_SECONDS,
    limit: int | None = None,
    sleep_fn=time.sleep,
    *,
    audit_config: AuditConfig | None = None,
    today: Callable[[], date] = date.today,
) -> StructuredBatchResult:
    """Collect structured evidence for every question still needing work.

    Pre-flight (no API call, no write): check limit and delay, load the
    question and results files, check question IDs are safe file names,
    refuse duplicate Gemini result rows, and classify every question.

    Then, in buyer_questions.csv order, attempt up to `limit` questions in
    state A or B (all of them if limit is None): process_question produces
    the complete row, which is saved immediately. A question that fails
    through the API, the analysis or row validation is recorded and the
    batch continues. A storage or integrity failure (evidence publishing,
    an evidence collision, the results file changing or failing to save,
    a would-be duplicate) stops the batch; everything saved before it is
    kept. KeyboardInterrupt is never caught.

    Raises AuditRunnerError, WriteAuditResultError or StructuredBatchError
    if pre-flight fails. Returns a StructuredBatchResult otherwise.
    """
    if limit is not None and limit < 0:
        raise StructuredBatchError(f"--limit must be 0 or more, got {limit}")
    if request_delay_seconds < 0:
        raise StructuredBatchError(f"--delay must be 0 or more, got {request_delay_seconds}")

    config = audit_config or default_audit_config()
    if question_csv_path is None:
        question_csv_path = config.questions_file
    if results_csv_path is None:
        results_csv_path = config.results_file
    evidence_dir = evidence_dir_for(results_csv_path)

    questions = load_questions(question_csv_path)
    validate_question_ids(questions)
    rows = load_existing_results(results_csv_path)
    duplicates = _duplicate_gemini_rows(rows)
    if duplicates:
        raise StructuredBatchError(f"{results_csv_path} has more than one Gemini row for: {', '.join(duplicates)}")

    result = StructuredBatchResult(total_questions=len(questions))
    states = [
        classify_question(q, rows, evidence_dir=evidence_dir, audit_slug=config.slug) for q in questions
    ]
    for state in states:
        result.initial_states.setdefault(state.state, []).append(state.question_id)
        if state.state == STATE_EVIDENCE_INTEGRITY_ERROR:
            result.integrity_problems.append((state.question_id, state.detail))

    eligible = [(q, s) for q, s in zip(questions, states) if s.state in ACTIONABLE_STATES]
    to_attempt = eligible if limit is None else eligible[:limit]

    print(f"Audit: {config.slug} ({config.company_name})")
    print(f"Questions: {question_csv_path}")
    print(f"Results: {results_csv_path}")
    print(f"Raw evidence: {evidence_dir}")
    print(f"Total questions: {len(questions)}")
    for state_code in ("C", "B", "A", "D", "E", "F"):
        print(f"  {state_code} {STATE_LABELS[state_code]}: {len(result.ids_in(state_code))}")
    limit_note = "" if limit is None else f" (limit {limit})"
    print(f"Needing work (A/B): {len(eligible)}; attempting {len(to_attempt)}{limit_note}")
    print()

    for index, (question_row, initial) in enumerate(to_attempt, start=1):
        question_id = question_row["question_id"]
        if index > 1:
            sleep_fn(request_delay_seconds)

        current = classify_question(question_row, rows, evidence_dir=evidence_dir, audit_slug=config.slug)
        if current.state not in ACTIONABLE_STATES:
            result.stopped = f"{question_id} changed state during the run ({current.state}: {current.detail})"
            print(f"[{index}/{len(to_attempt)}] {question_id}: STOPPED - {result.stopped}")
            break

        action = "answering" if current.state == STATE_NOT_STARTED else "analysing stored answer"
        print(f"[{index}/{len(to_attempt)}] {question_id}: {action}...")
        result.attempted.append(question_id)
        try:
            row = process_question(
                question_row, config, rows, evidence_dir=evidence_dir, sleep_fn=sleep_fn, today=today
            )
            rows = _persist_row(results_csv_path, rows, row)
        except _QUESTION_FAILURES as exc:
            result.failed.append((question_id, str(exc)))
            print(f"[{index}/{len(to_attempt)}] {question_id}: FAILED - {exc}")
            continue
        except (StructuredBatchError, *_STORAGE_FAILURES) as exc:
            result.stopped = f"{question_id}: {exc}"
            print(f"[{index}/{len(to_attempt)}] {question_id}: STOPPED - {exc}")
            break

        if current.state == STATE_NOT_STARTED:
            result.completed_new_answers.append(question_id)
        else:
            result.completed_from_stored.append(question_id)
        print(f"[{index}/{len(to_attempt)}] {question_id}: SAVED")

    completed = set(result.completed)
    result.pending_after = sum(1 for _, s in eligible if s.question_id not in completed)
    _print_summary(result)
    return result


def _print_summary(result: StructuredBatchResult) -> None:
    print()
    print(
        f"Completed this run: {len(result.completed)} "
        f"(new answers: {len(result.completed_new_answers)}, from stored answers: {len(result.completed_from_stored)})"
    )
    print(f"Failed this run: {len(result.failed)}" + (
        f" - {', '.join(qid for qid, _ in result.failed)}" if result.failed else ""))
    print(f"Still needing work (A/B): {result.pending_after}")
    print(f"Complete with evidence at start (C): {len(result.ids_in(STATE_COMPLETE_WITH_EVIDENCE))}")
    print(f"Complete without stored full answer (E): {len(result.ids_in(STATE_LEGACY_COMPLETE_NO_EVIDENCE))}")
    legacy = result.ids_in(STATE_LEGACY_INCOMPLETE)
    print(f"Legacy incomplete, not reprocessed (D): {len(legacy)}" + (f" - {', '.join(legacy)}" if legacy else ""))
    print(f"Evidence integrity problems (F): {len(result.integrity_problems)}" + (
        f" - {', '.join(qid for qid, _ in result.integrity_problems)}" if result.integrity_problems else ""))
    for question_id, detail in result.integrity_problems:
        print(f"  {question_id}: {detail}")
    if result.stopped:
        print(f"STOPPED: {result.stopped}")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Structured batch evidence collection for SignalScope AI: asks Gemini each pending "
        "buyer question, stores the full answer, analyses it and saves one structured row per question."
    )
    parser.add_argument("--audit", default=None, help="Audit slug under audits/ (default: the default audit)")
    parser.add_argument("--questions", default=None, help="Path to buyer_questions.csv (default: the audit's file)")
    parser.add_argument("--results", default=None, help="Path to audit_results.csv (default: the audit's file)")
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_REQUEST_DELAY_SECONDS,
        help=f"Seconds to wait between questions (default: {DEFAULT_REQUEST_DELAY_SECONDS:g})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Attempt at most N questions still needing work (default: all). Each costs up to 2 Gemini calls.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = parse_args(argv)

    try:
        audit_config = load_audit_config(args.audit) if args.audit is not None else None
        result = run_structured_batch_audit(
            question_csv_path=args.questions,
            results_csv_path=args.results,
            request_delay_seconds=args.delay,
            limit=args.limit,
            audit_config=audit_config,
        )
    except (AuditConfigError, AuditRunnerError, WriteAuditResultError, StructuredBatchError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())

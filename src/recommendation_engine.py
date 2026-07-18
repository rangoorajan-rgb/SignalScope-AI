"""GEO recommendation engine for SignalScope AI.

Consumes the structured findings produced by geo_findings_analyzer.py -
never GEO_FINDINGS.md - and turns them into structured, prioritised GEO
recommendations. Gemini is used for the interpretive/creative content
only (title, problem framing, rationale, recommended action, success
metric, and an indicative impact/effort read); the fields that must stay
strictly evidence-bound - supporting_evidence, confidence, and priority -
are computed deterministically in Python from the findings actually
cited, never left to the model.

Gemini receives only the structured findings plus the brand/market/
category - no raw audit rows, no answer snippets, and no web access.
This module does not browse the web or collect new evidence.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from audit_runner import AuditRunnerError, load_questions
from gemini_client import GeminiClientError, generate_response
from geo_findings_analyzer import Finding, compute_findings
from report_generator import BRAND, CATEGORY, MARKET, ReportGeneratorError, load_audit_rows
from write_single_audit_result import WriteAuditResultError

DEFAULT_QUESTIONS_FILE = "audits/boots-uk-health-beauty/buyer_questions.csv"
DEFAULT_RESULTS_FILE = "audits/boots-uk-health-beauty/audit_results.csv"
DEFAULT_RECOMMENDATIONS_REPORT_FILE = "reports/boots-uk-health-beauty/GEO_RECOMMENDATIONS.md"

VALID_LEVELS = {"High", "Medium", "Low"}
LEVEL_SCORES = {"High": 3, "Medium": 2, "Low": 1}
CONFIDENCE_ORDER = ["Low", "Medium", "High"]  # ascending, for min()
PRIORITY_SORT_ORDER = {"P1": 0, "P2": 1, "P3": 2}

EXPECTED_FIELDS = {
    "title",
    "problem_addressed",
    "recommendation_rationale",
    "recommended_action",
    "potential_impact",
    "indicative_effort",
    "success_metric",
    "source_findings",
}

_FENCE_PATTERN = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


class RecommendationEngineError(Exception):
    """Raised for problems generating GEO recommendations."""


@dataclass(frozen=True)
class Recommendation:
    """One structured GEO recommendation, traceable to the finding(s) it
    is based on. confidence and priority are computed deterministically
    from those findings - never proposed by the model."""

    title: str
    problem_addressed: str
    supporting_evidence: str
    recommendation_rationale: str
    recommended_action: str
    potential_impact: str  # High / Medium / Low
    indicative_effort: str  # High / Medium / Low
    confidence: str  # High / Medium / Low
    priority: str  # P1 / P2 / P3
    success_metric: str
    source_findings: list[str]


def _build_recommendations_prompt(findings: list[Finding], brand: str, market: str, category: str) -> str:
    findings_block = "\n\n".join(
        f'Finding title: "{f.title}"\n'
        f"Observation: {f.value}\n"
        f"Evidence: {f.evidence}\n"
        f"Confidence: {f.confidence}"
        for f in findings
    )

    return f"""You are a GEO (Generative Engine Optimisation) analyst producing
recommendations for a brand visibility audit. You are given a fixed set of
structured findings and must propose recommendations grounded ONLY in
those findings. Do not invent facts about the brand, its website,
competitors, or any external source beyond what is stated in the findings
below.

Brand: {brand}
Market: {market}
Category: {category}

FINDINGS:
{findings_block}

Propose a JSON array of recommendation objects - as many as are genuinely
warranted by the findings (typically 3 to 7), each in exactly this shape:

[
  {{
    "title": "short recommendation title",
    "problem_addressed": "the gap or issue this responds to, in business language",
    "recommendation_rationale": "why this recommendation follows from the cited finding(s)",
    "recommended_action": "the concrete action to take",
    "potential_impact": "High, Medium, or Low",
    "indicative_effort": "High, Medium, or Low",
    "success_metric": "how a consultant would measure whether this worked",
    "source_findings": ["<one or more of the exact finding titles above>"]
  }}
]

Rules:
- "source_findings" must only contain finding titles exactly as given above.
- Every recommendation must be grounded in at least one cited finding - do
  not propose a recommendation that is not traceable to the findings given.
- "potential_impact" and "indicative_effort" must each be exactly "High",
  "Medium", or "Low".
- Do not invent facts about the brand's website, technical setup, content,
  or any competitor beyond what the findings state.
- Return only the JSON array, nothing else - no markdown code fences, no
  explanation."""


def _parse_json_array(raw: str) -> object:
    """Parse Gemini's recommendations output as a JSON array, tolerating
    markdown fences or minor surrounding prose, without inventing
    structure that isn't actually present in the text."""
    stripped = raw.strip()
    fence_match = _FENCE_PATTERN.match(stripped)
    candidate = fence_match.group(1).strip() if fence_match else stripped

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    start, end = raw.find("["), raw.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError as exc:
            raise RecommendationEngineError(
                f"Gemini recommendations response was malformed JSON: {exc}\nRaw response: {raw!r}"
            ) from exc

    raise RecommendationEngineError(
        f"Gemini recommendations response was malformed JSON.\nRaw response: {raw!r}"
    )


def _validate_non_empty_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RecommendationEngineError(
            f"Invalid {field_name} value: expected a non-empty string, got {value!r}"
        )
    return value.strip()


def _validate_level(value: object, field_name: str) -> str:
    if value not in VALID_LEVELS:
        raise RecommendationEngineError(
            f"Invalid {field_name} value: {value!r} (expected one of {sorted(VALID_LEVELS)})"
        )
    return value


def _validate_source_findings(value: object, known_titles: set[str]) -> list[str]:
    if not isinstance(value, list) or not value:
        raise RecommendationEngineError(
            f"Invalid source_findings value: expected a non-empty list, got {value!r}"
        )
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise RecommendationEngineError(f"Invalid source_findings entry: {item!r} is not a string")
        if item not in known_titles:
            raise RecommendationEngineError(
                f"Invalid source_findings entry: {item!r} does not match a known finding title"
            )
        if item not in result:
            result.append(item)
    return result


def _min_confidence(source_titles: list[str], findings_by_title: dict[str, Finding]) -> str:
    confidences = [findings_by_title[t].confidence for t in source_titles]
    return min(confidences, key=CONFIDENCE_ORDER.index)


def _build_supporting_evidence(source_titles: list[str], findings_by_title: dict[str, Finding]) -> str:
    return " | ".join(f"[{t}] {findings_by_title[t].evidence}" for t in source_titles)


def _compute_priority(potential_impact: str, confidence: str, indicative_effort: str) -> str:
    composite = LEVEL_SCORES[potential_impact] + LEVEL_SCORES[confidence] - LEVEL_SCORES[indicative_effort]
    if composite >= 4:
        return "P1"
    if composite >= 2:
        return "P2"
    return "P3"


def _build_recommendation(item: object, findings_by_title: dict[str, Finding]) -> Recommendation:
    if not isinstance(item, dict):
        raise RecommendationEngineError(f"Recommendation entry was not a JSON object: {item!r}")

    actual_fields = set(item.keys())
    missing = EXPECTED_FIELDS - actual_fields
    if missing:
        raise RecommendationEngineError(f"Recommendation entry is missing field(s): {sorted(missing)}")
    unexpected = actual_fields - EXPECTED_FIELDS
    if unexpected:
        raise RecommendationEngineError(f"Recommendation entry has unexpected field(s): {sorted(unexpected)}")

    title = _validate_non_empty_string(item["title"], "title")
    problem_addressed = _validate_non_empty_string(item["problem_addressed"], "problem_addressed")
    recommendation_rationale = _validate_non_empty_string(
        item["recommendation_rationale"], "recommendation_rationale"
    )
    recommended_action = _validate_non_empty_string(item["recommended_action"], "recommended_action")
    success_metric = _validate_non_empty_string(item["success_metric"], "success_metric")
    potential_impact = _validate_level(item["potential_impact"], "potential_impact")
    indicative_effort = _validate_level(item["indicative_effort"], "indicative_effort")
    source_findings = _validate_source_findings(item["source_findings"], set(findings_by_title.keys()))

    confidence = _min_confidence(source_findings, findings_by_title)
    supporting_evidence = _build_supporting_evidence(source_findings, findings_by_title)
    priority = _compute_priority(potential_impact, confidence, indicative_effort)

    return Recommendation(
        title=title,
        problem_addressed=problem_addressed,
        supporting_evidence=supporting_evidence,
        recommendation_rationale=recommendation_rationale,
        recommended_action=recommended_action,
        potential_impact=potential_impact,
        indicative_effort=indicative_effort,
        confidence=confidence,
        priority=priority,
        success_metric=success_metric,
        source_findings=source_findings,
    )


def generate_recommendations(
    findings: list[Finding],
    brand: str = BRAND,
    market: str = MARKET,
    category: str = CATEGORY,
) -> list[Recommendation]:
    """Generate structured, prioritised recommendations from findings.

    Calls Gemini exactly once, receiving only the findings' title/value/
    evidence/confidence plus brand/market/category - no raw audit rows,
    no web access. Validates the response strictly and computes
    supporting_evidence, confidence, and priority deterministically from
    the cited findings, never from the model's own claims.

    Raises RecommendationEngineError for an empty findings list, a
    Gemini/API failure, malformed JSON, or any invalid field. Returns the
    recommendations sorted P1 -> P3 (stable on ties).
    """
    if not findings:
        raise RecommendationEngineError("Cannot generate recommendations from an empty findings list.")

    findings_by_title = {f.title: f for f in findings}
    prompt = _build_recommendations_prompt(findings, brand, market, category)

    try:
        raw = generate_response(prompt)
    except GeminiClientError as exc:
        raise RecommendationEngineError(f"Gemini recommendation call failed: {exc}") from exc

    if not raw or not raw.strip():
        raise RecommendationEngineError("Gemini recommendation call returned an empty response.")

    parsed = _parse_json_array(raw)
    if not isinstance(parsed, list) or not parsed:
        raise RecommendationEngineError(
            f"Gemini recommendations response was not a non-empty JSON array: {parsed!r}"
        )

    recommendations = [_build_recommendation(item, findings_by_title) for item in parsed]
    recommendations.sort(key=lambda r: PRIORITY_SORT_ORDER[r.priority])
    return recommendations


def render_markdown(recommendations: list[Recommendation], total_findings: int, generated_at: date) -> str:
    """Render the Markdown GEO recommendations report purely from an
    already-computed list[Recommendation] - the structured recommendations
    are the source of truth, not this text."""
    priority_counts = Counter(r.priority for r in recommendations)

    lines: list[str] = []
    lines.append("# SignalScope AI GEO Recommendations Report — Boots UK Health & Beauty")
    lines.append("")

    lines.append("## Report Overview")
    lines.append("")
    lines.append(f"- Brand: {BRAND}")
    lines.append(f"- Market: {MARKET}")
    lines.append(f"- Category: {CATEGORY}")
    lines.append(f"- Findings analysed: {total_findings}")
    lines.append(f"- Recommendations generated: {len(recommendations)}")
    lines.append(f"- Report generation date: {generated_at.isoformat()}")
    lines.append("")

    lines.append("## Executive Summary")
    lines.append("")
    lines.append(
        f"This report translates {total_findings} structured GEO finding(s) into "
        f"{len(recommendations)} prioritised recommendation(s): "
        f"{priority_counts.get('P1', 0)} P1, {priority_counts.get('P2', 0)} P2, "
        f"{priority_counts.get('P3', 0)} P3. Each recommendation is traceable to the "
        f"specific finding(s) it is based on, and its confidence reflects the "
        f"confidence of the weakest finding it relies on."
    )
    lines.append("")

    lines.append("## Prioritised Recommendations")
    lines.append("")
    lines.append("| Priority | Title | Potential Impact | Indicative Effort | Confidence |")
    lines.append("|---|---|---|---|---|")
    for r in recommendations:
        lines.append(f"| {r.priority} | {r.title} | {r.potential_impact} | {r.indicative_effort} | {r.confidence} |")
    lines.append("")

    lines.append("## Detailed Recommendations")
    lines.append("")
    for index, r in enumerate(recommendations, start=1):
        lines.append(f"### {index}. [{r.priority}] {r.title}")
        lines.append("")
        lines.append(f"- **Problem Addressed:** {r.problem_addressed}")
        lines.append(f"- **Supporting Evidence:** {r.supporting_evidence}")
        lines.append(f"- **Recommendation Rationale:** {r.recommendation_rationale}")
        lines.append(f"- **Recommended Action:** {r.recommended_action}")
        lines.append(f"- **Potential Impact:** {r.potential_impact}")
        lines.append(f"- **Indicative Effort:** {r.indicative_effort}")
        lines.append(f"- **Confidence:** {r.confidence}")
        lines.append(f"- **Success Metric:** {r.success_metric}")
        lines.append(f"- **Source Finding(s):** {', '.join(r.source_findings)}")
        lines.append("")

    lines.append("## Implementation Note")
    lines.append("")
    lines.append(
        "These are recommendations only. The brand or its consultant must implement "
        "the actions above before any re-audit can measure whether AI search "
        "visibility has changed. SignalScope AI does not implement changes, publish "
        "content, or edit any website on the brand's behalf."
    )
    lines.append("")

    return "\n".join(lines)


def generate_geo_recommendations(
    questions_csv_path: str = DEFAULT_QUESTIONS_FILE,
    results_csv_path: str = DEFAULT_RESULTS_FILE,
    report_path: str = DEFAULT_RECOMMENDATIONS_REPORT_FILE,
    generated_at: date | None = None,
) -> tuple[list[Recommendation], str]:
    """Load the audit dataset, compute findings, generate recommendations,
    and render + write the Markdown report.

    Returns (recommendations, markdown_text). Raises AuditRunnerError for
    a missing/invalid question file, WriteAuditResultError for a missing/
    schema-invalid results file, ReportGeneratorError if the results file
    has no data rows, or RecommendationEngineError for any problem
    generating the recommendations themselves.
    """
    generated_at = generated_at or date.today()

    all_questions = load_questions(questions_csv_path)
    rows = load_audit_rows(results_csv_path)
    findings = compute_findings(rows, len(all_questions))

    recommendations = generate_recommendations(findings)
    markdown = render_markdown(recommendations, len(findings), generated_at)

    out_path = Path(report_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown, encoding="utf-8")

    return recommendations, markdown


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    questions_csv_path = argv[0] if len(argv) > 0 else DEFAULT_QUESTIONS_FILE
    results_csv_path = argv[1] if len(argv) > 1 else DEFAULT_RESULTS_FILE
    report_path = argv[2] if len(argv) > 2 else DEFAULT_RECOMMENDATIONS_REPORT_FILE

    try:
        recommendations, _ = generate_geo_recommendations(questions_csv_path, results_csv_path, report_path)
    except (AuditRunnerError, WriteAuditResultError, ReportGeneratorError, RecommendationEngineError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"GEO recommendations report written to: {report_path}")
    for r in recommendations:
        print(
            f"- [{r.priority}] {r.title} "
            f"(impact={r.potential_impact}, effort={r.indicative_effort}, confidence={r.confidence})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

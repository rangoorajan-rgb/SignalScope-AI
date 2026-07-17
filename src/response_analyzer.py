"""Structured response analysis for SignalScope AI.

Uses Gemini as a second, separate pass to extract structured observations
(brand citation, position, competitors, sources, sentiment) from a raw
answer already generated for a buyer question. Generation and analysis are
kept as two distinct steps, consistent with the project's documented
two-pass methodology (see docs/METHODOLOGY.md): each can be checked
independently, and this module never originates an unverified claim of
its own — it only structures what Gemini reports finding in the text it
is given.
"""

from __future__ import annotations

import json
import re

from gemini_client import GeminiClientError, generate_response

VALID_SENTIMENTS = {"Positive", "Neutral", "Negative"}
VALID_BRAND_CITED = {"Y", "N"}
EXPECTED_FIELDS = {
    "brand_cited",
    "brand_position",
    "competitors_cited",
    "sources_cited",
    "sentiment",
}

_FENCE_PATTERN = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


class ResponseAnalysisError(Exception):
    """Raised for problems analysing a Gemini response into structured fields."""


def _build_analysis_prompt(response_text: str, brand: str, known_competitors: list[str]) -> str:
    competitors_list = ", ".join(known_competitors)
    return f"""You are analysing a single AI-generated answer for a brand visibility audit.
Analyse the ANSWER TEXT below and return ONLY a single strict JSON object,
with no markdown code fences, no explanation, and no extra text, in exactly
this shape:

{{
  "brand_cited": "Y or N",
  "brand_position": <positive integer or null>,
  "competitors_cited": ["competitor names"],
  "sources_cited": ["explicit source names or URLs"],
  "sentiment": "Positive, Neutral, or Negative"
}}

Definitions:
- brand_cited: "Y" only if "{brand}" is explicitly named anywhere in the
  answer text, otherwise "N".
- brand_position: the ordinal position (1, 2, 3, ...) in which "{brand}"
  first appears among explicitly named retailer/vendor recommendations in
  the answer text. Use null if "{brand}" is not cited, or if the answer
  text contains no ranked or ordered list of retailers/vendors. Do not
  infer a ranking that is not actually present in the text.
- competitors_cited: explicitly named alternative or competing retailers
  mentioned in the answer text, excluding "{brand}" itself. Include any
  competitor named in the text even if it is not in this known list:
  [{competitors_list}]. Do not invent competitors that are not named in
  the text. Remove duplicates, preserving the order they first appear in.
- sources_cited: source names, publications, organisations, or URLs
  explicitly stated in the answer text. Do not invent or infer sources.
  Return an empty list if none are explicitly present.
- sentiment: the answer text's overall treatment of "{brand}" — "Positive",
  "Neutral", or "Negative". If "{brand}" is not mentioned, use "Neutral".

ANSWER TEXT:
\"\"\"
{response_text}
\"\"\"

Return only the JSON object, nothing else."""


def _parse_json(raw: str) -> object:
    """Parse Gemini's analysis output as JSON, tolerating markdown fences
    or minor surrounding prose, but never inventing structure that isn't
    actually present in the text."""
    stripped = raw.strip()
    fence_match = _FENCE_PATTERN.match(stripped)
    candidate = fence_match.group(1).strip() if fence_match else stripped

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ResponseAnalysisError(
                f"Gemini analysis returned malformed JSON: {exc}\nRaw response: {raw!r}"
            ) from exc

    raise ResponseAnalysisError(f"Gemini analysis returned malformed JSON.\nRaw response: {raw!r}")


def _validate_brand_position(value: object, brand_cited: str) -> "int | str":
    if value is None or value == "":
        position: "int | str" = ""
    elif isinstance(value, bool):
        raise ResponseAnalysisError(
            f"Invalid brand_position value: {value!r} (expected a positive integer or blank)"
        )
    elif isinstance(value, int):
        position = value
    elif isinstance(value, float) and value.is_integer():
        position = int(value)
    elif isinstance(value, str) and value.strip().isdigit():
        position = int(value.strip())
    else:
        raise ResponseAnalysisError(
            f"Invalid brand_position value: {value!r} (expected a positive integer or blank)"
        )

    if position != "" and position < 1:
        raise ResponseAnalysisError(
            f"Invalid brand_position value: {value!r} (must be a positive integer)"
        )

    if brand_cited == "N" and position != "":
        raise ResponseAnalysisError(
            "Invalid brand_position: a position was given but brand_cited is 'N'."
        )

    return position


def _normalise_string_list(value: object, field_name: str, exclude: set[str] | None = None) -> list[str]:
    if not isinstance(value, list):
        raise ResponseAnalysisError(
            f"Invalid {field_name} value: expected a list, got {type(value).__name__}"
        )

    exclude_lower = {e.strip().lower() for e in (exclude or set())}
    seen: set[str] = set()
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ResponseAnalysisError(
                f"Invalid {field_name} entry: expected a string, got {type(item).__name__}: {item!r}"
            )
        cleaned = item.strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in exclude_lower or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)

    return result


def _validate_and_normalise(data: object, brand: str) -> dict:
    if not isinstance(data, dict):
        raise ResponseAnalysisError("Gemini analysis response was not a JSON object.")

    actual_fields = set(data.keys())
    missing = EXPECTED_FIELDS - actual_fields
    if missing:
        raise ResponseAnalysisError(
            f"Gemini analysis response is missing field(s): {sorted(missing)}"
        )
    unexpected = actual_fields - EXPECTED_FIELDS
    if unexpected:
        raise ResponseAnalysisError(
            f"Gemini analysis response has unexpected field(s): {sorted(unexpected)}"
        )

    brand_cited = data["brand_cited"]
    if brand_cited not in VALID_BRAND_CITED:
        raise ResponseAnalysisError(
            f"Invalid brand_cited value: {brand_cited!r} (expected 'Y' or 'N')"
        )

    brand_position = _validate_brand_position(data["brand_position"], brand_cited)
    competitors_cited = _normalise_string_list(
        data["competitors_cited"], "competitors_cited", exclude={brand}
    )
    sources_cited = _normalise_string_list(data["sources_cited"], "sources_cited")

    sentiment = data["sentiment"]
    if sentiment not in VALID_SENTIMENTS:
        raise ResponseAnalysisError(
            f"Invalid sentiment value: {sentiment!r} (expected one of {sorted(VALID_SENTIMENTS)})"
        )

    return {
        "brand_cited": brand_cited,
        "brand_position": brand_position,
        "competitors_cited": competitors_cited,
        "sources_cited": sources_cited,
        "sentiment": sentiment,
    }


def analyze_response(response_text: str, brand: str, known_competitors: list[str]) -> dict:
    """Extract structured fields from a raw Gemini answer via a second Gemini pass.

    Returns a dict with keys: brand_cited, brand_position, competitors_cited,
    sources_cited, sentiment (see the module docstring for their meaning).

    Raises ResponseAnalysisError if response_text is empty, the analysis
    call fails, the analysis response is empty, its JSON is malformed, or
    any field fails validation.
    """
    if not response_text or not response_text.strip():
        raise ResponseAnalysisError("Cannot analyse an empty response.")

    prompt = _build_analysis_prompt(response_text, brand, known_competitors)

    try:
        raw = generate_response(prompt)
    except GeminiClientError as exc:
        raise ResponseAnalysisError(f"Gemini analysis call failed: {exc}") from exc

    if not raw or not raw.strip():
        raise ResponseAnalysisError("Gemini analysis returned an empty response.")

    data = _parse_json(raw)
    return _validate_and_normalise(data, brand)

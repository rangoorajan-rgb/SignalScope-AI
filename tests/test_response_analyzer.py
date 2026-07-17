"""Tests for src/response_analyzer.py.

No real API calls are made: generate_response is mocked throughout.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from gemini_client import GeminiClientError  # noqa: E402
from response_analyzer import ResponseAnalysisError, analyze_response  # noqa: E402

BRAND = "Boots"
KNOWN_COMPETITORS = ["Superdrug", "Amazon", "Holland & Barrett"]


def canned_json(**overrides) -> str:
    payload = {
        "brand_cited": "Y",
        "brand_position": 1,
        "competitors_cited": ["Superdrug"],
        "sources_cited": [],
        "sentiment": "Positive",
    }
    payload.update(overrides)
    return json.dumps(payload)


class AnalyzeResponseTests(unittest.TestCase):
    def test_rejects_empty_response_text(self) -> None:
        with self.assertRaises(ResponseAnalysisError):
            analyze_response("   ", BRAND, KNOWN_COMPETITORS)

    @patch("response_analyzer.generate_response")
    def test_boots_cited_and_ranked_first(self, mock_generate) -> None:
        mock_generate.return_value = canned_json(brand_cited="Y", brand_position=1)
        result = analyze_response("Boots is the top pick.", BRAND, KNOWN_COMPETITORS)
        self.assertEqual(result["brand_cited"], "Y")
        self.assertEqual(result["brand_position"], 1)

    @patch("response_analyzer.generate_response")
    def test_boots_cited_without_valid_ranking(self, mock_generate) -> None:
        mock_generate.return_value = canned_json(brand_cited="Y", brand_position=None)
        result = analyze_response("Boots is mentioned, no ranked list.", BRAND, KNOWN_COMPETITORS)
        self.assertEqual(result["brand_cited"], "Y")
        self.assertEqual(result["brand_position"], "")

    @patch("response_analyzer.generate_response")
    def test_boots_not_cited(self, mock_generate) -> None:
        mock_generate.return_value = canned_json(
            brand_cited="N", brand_position=None, sentiment="Neutral", competitors_cited=[]
        )
        result = analyze_response("No mention of the brand at all.", BRAND, KNOWN_COMPETITORS)
        self.assertEqual(result["brand_cited"], "N")
        self.assertEqual(result["brand_position"], "")

    @patch("response_analyzer.generate_response")
    def test_competitors_deduplicated_preserving_order(self, mock_generate) -> None:
        mock_generate.return_value = canned_json(
            competitors_cited=["Superdrug", "Amazon", "superdrug", "Amazon"]
        )
        result = analyze_response("text", BRAND, KNOWN_COMPETITORS)
        self.assertEqual(result["competitors_cited"], ["Superdrug", "Amazon"])

    @patch("response_analyzer.generate_response")
    def test_additional_competitor_not_in_known_list(self, mock_generate) -> None:
        mock_generate.return_value = canned_json(competitors_cited=["Lookfantastic"])
        result = analyze_response("text", BRAND, KNOWN_COMPETITORS)
        self.assertEqual(result["competitors_cited"], ["Lookfantastic"])

    @patch("response_analyzer.generate_response")
    def test_brand_excluded_from_competitors_even_if_returned(self, mock_generate) -> None:
        mock_generate.return_value = canned_json(competitors_cited=["Boots", "Superdrug"])
        result = analyze_response("text", BRAND, KNOWN_COMPETITORS)
        self.assertEqual(result["competitors_cited"], ["Superdrug"])

    @patch("response_analyzer.generate_response")
    def test_explicit_sources_extracted(self, mock_generate) -> None:
        mock_generate.return_value = canned_json(
            sources_cited=["Mintel", "https://example.com/report"]
        )
        result = analyze_response("text", BRAND, KNOWN_COMPETITORS)
        self.assertEqual(result["sources_cited"], ["Mintel", "https://example.com/report"])

    @patch("response_analyzer.generate_response")
    def test_no_sources_returns_empty_list(self, mock_generate) -> None:
        mock_generate.return_value = canned_json(sources_cited=[])
        result = analyze_response("text", BRAND, KNOWN_COMPETITORS)
        self.assertEqual(result["sources_cited"], [])

    @patch("response_analyzer.generate_response")
    def test_positive_sentiment(self, mock_generate) -> None:
        mock_generate.return_value = canned_json(sentiment="Positive")
        result = analyze_response("text", BRAND, KNOWN_COMPETITORS)
        self.assertEqual(result["sentiment"], "Positive")

    @patch("response_analyzer.generate_response")
    def test_neutral_sentiment(self, mock_generate) -> None:
        mock_generate.return_value = canned_json(sentiment="Neutral")
        result = analyze_response("text", BRAND, KNOWN_COMPETITORS)
        self.assertEqual(result["sentiment"], "Neutral")

    @patch("response_analyzer.generate_response")
    def test_negative_sentiment(self, mock_generate) -> None:
        mock_generate.return_value = canned_json(sentiment="Negative")
        result = analyze_response("text", BRAND, KNOWN_COMPETITORS)
        self.assertEqual(result["sentiment"], "Negative")

    @patch("response_analyzer.generate_response")
    def test_strips_markdown_code_fences(self, mock_generate) -> None:
        mock_generate.return_value = "```json\n" + canned_json() + "\n```"
        result = analyze_response("text", BRAND, KNOWN_COMPETITORS)
        self.assertEqual(result["brand_cited"], "Y")

    @patch("response_analyzer.generate_response")
    def test_extracts_json_surrounded_by_prose(self, mock_generate) -> None:
        mock_generate.return_value = "Sure, here is the analysis:\n" + canned_json() + "\nHope that helps!"
        result = analyze_response("text", BRAND, KNOWN_COMPETITORS)
        self.assertEqual(result["brand_cited"], "Y")

    @patch("response_analyzer.generate_response")
    def test_malformed_json_raises(self, mock_generate) -> None:
        mock_generate.return_value = "{not: valid json,,,"
        with self.assertRaises(ResponseAnalysisError):
            analyze_response("text", BRAND, KNOWN_COMPETITORS)

    @patch("response_analyzer.generate_response")
    def test_missing_field_raises(self, mock_generate) -> None:
        payload = json.loads(canned_json())
        del payload["sentiment"]
        mock_generate.return_value = json.dumps(payload)
        with self.assertRaises(ResponseAnalysisError):
            analyze_response("text", BRAND, KNOWN_COMPETITORS)

    @patch("response_analyzer.generate_response")
    def test_unexpected_field_raises(self, mock_generate) -> None:
        payload = json.loads(canned_json())
        payload["extra_field"] = "surprise"
        mock_generate.return_value = json.dumps(payload)
        with self.assertRaises(ResponseAnalysisError):
            analyze_response("text", BRAND, KNOWN_COMPETITORS)

    @patch("response_analyzer.generate_response")
    def test_invalid_brand_cited_raises(self, mock_generate) -> None:
        mock_generate.return_value = canned_json(brand_cited="Maybe")
        with self.assertRaises(ResponseAnalysisError):
            analyze_response("text", BRAND, KNOWN_COMPETITORS)

    @patch("response_analyzer.generate_response")
    def test_zero_brand_position_raises(self, mock_generate) -> None:
        mock_generate.return_value = canned_json(brand_position=0)
        with self.assertRaises(ResponseAnalysisError):
            analyze_response("text", BRAND, KNOWN_COMPETITORS)

    @patch("response_analyzer.generate_response")
    def test_negative_brand_position_raises(self, mock_generate) -> None:
        mock_generate.return_value = canned_json(brand_position=-1)
        with self.assertRaises(ResponseAnalysisError):
            analyze_response("text", BRAND, KNOWN_COMPETITORS)

    @patch("response_analyzer.generate_response")
    def test_non_numeric_brand_position_raises(self, mock_generate) -> None:
        mock_generate.return_value = canned_json(brand_position="first")
        with self.assertRaises(ResponseAnalysisError):
            analyze_response("text", BRAND, KNOWN_COMPETITORS)

    @patch("response_analyzer.generate_response")
    def test_brand_position_present_but_not_cited_raises(self, mock_generate) -> None:
        mock_generate.return_value = canned_json(brand_cited="N", brand_position=2)
        with self.assertRaises(ResponseAnalysisError):
            analyze_response("text", BRAND, KNOWN_COMPETITORS)

    @patch("response_analyzer.generate_response")
    def test_invalid_sentiment_raises(self, mock_generate) -> None:
        mock_generate.return_value = canned_json(sentiment="Mixed")
        with self.assertRaises(ResponseAnalysisError):
            analyze_response("text", BRAND, KNOWN_COMPETITORS)

    @patch("response_analyzer.generate_response")
    def test_generation_failure_raises_response_analysis_error(self, mock_generate) -> None:
        mock_generate.side_effect = GeminiClientError("Gemini API call failed: 503 UNAVAILABLE.")
        with self.assertRaises(ResponseAnalysisError):
            analyze_response("text", BRAND, KNOWN_COMPETITORS)

    @patch("response_analyzer.generate_response")
    def test_non_list_competitors_raises(self, mock_generate) -> None:
        payload = json.loads(canned_json())
        payload["competitors_cited"] = "Superdrug"
        mock_generate.return_value = json.dumps(payload)
        with self.assertRaises(ResponseAnalysisError):
            analyze_response("text", BRAND, KNOWN_COMPETITORS)

    @patch("response_analyzer.generate_response")
    def test_non_string_list_item_raises(self, mock_generate) -> None:
        payload = json.loads(canned_json())
        payload["sources_cited"] = ["Mintel", 123]
        mock_generate.return_value = json.dumps(payload)
        with self.assertRaises(ResponseAnalysisError):
            analyze_response("text", BRAND, KNOWN_COMPETITORS)

    @patch("response_analyzer.generate_response")
    def test_non_dict_json_raises(self, mock_generate) -> None:
        mock_generate.return_value = json.dumps(["not", "a", "dict"])
        with self.assertRaises(ResponseAnalysisError):
            analyze_response("text", BRAND, KNOWN_COMPETITORS)

    @patch("response_analyzer.generate_response")
    def test_empty_analysis_response_raises(self, mock_generate) -> None:
        mock_generate.return_value = "   "
        with self.assertRaises(ResponseAnalysisError):
            analyze_response("text", BRAND, KNOWN_COMPETITORS)


if __name__ == "__main__":
    unittest.main()

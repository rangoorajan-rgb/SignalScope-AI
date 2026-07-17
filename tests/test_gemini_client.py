"""Tests for src/gemini_client.py.

No real API calls are made: the Gemini SDK client is mocked throughout.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import gemini_client  # noqa: E402
from gemini_client import GeminiClientError, generate_response  # noqa: E402

NONEXISTENT_ENV_FILE = Path(tempfile.gettempdir()) / "signalscope_test_does_not_exist" / ".env"


class LoadDotenvTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_loads_variables_from_file(self) -> None:
        env_file = self.tmp_path / ".env"
        env_file.write_text(
            "# comment line\n\nGEMINI_API_KEY=file-value\nOTHER_VAR=\"quoted\"\n",
            encoding="utf-8",
        )

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GEMINI_API_KEY", None)
            os.environ.pop("OTHER_VAR", None)
            gemini_client._load_dotenv(env_file)
            self.assertEqual(os.environ.get("GEMINI_API_KEY"), "file-value")
            self.assertEqual(os.environ.get("OTHER_VAR"), "quoted")

    def test_does_not_override_existing_env_var(self) -> None:
        env_file = self.tmp_path / ".env"
        env_file.write_text("GEMINI_API_KEY=file-value\n", encoding="utf-8")

        with patch.dict(os.environ, {"GEMINI_API_KEY": "already-set"}):
            gemini_client._load_dotenv(env_file)
            self.assertEqual(os.environ.get("GEMINI_API_KEY"), "already-set")

    def test_missing_file_is_a_no_op(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GEMINI_API_KEY", None)
            gemini_client._load_dotenv(self.tmp_path / "does_not_exist.env")
            self.assertIsNone(os.environ.get("GEMINI_API_KEY"))


class GenerateResponseTests(unittest.TestCase):
    def test_missing_api_key_raises(self) -> None:
        with patch.object(gemini_client, "ENV_FILE", NONEXISTENT_ENV_FILE):
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("GEMINI_API_KEY", None)
                with self.assertRaises(GeminiClientError) as ctx:
                    generate_response("hello")
                self.assertIn("GEMINI_API_KEY", str(ctx.exception))

    @patch("gemini_client.genai.Client")
    def test_returns_response_text_on_success(self, mock_client_cls: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.text = "SignalScope AI connection successful."
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_client_cls.return_value = mock_client

        with patch.object(gemini_client, "ENV_FILE", NONEXISTENT_ENV_FILE):
            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}):
                result = generate_response("Reply with exactly: SignalScope AI connection successful.")

        self.assertEqual(result, "SignalScope AI connection successful.")
        mock_client_cls.assert_called_once_with(api_key="test-key")
        mock_client.models.generate_content.assert_called_once()

    @patch("gemini_client.genai.Client")
    def test_sdk_error_raises_gemini_client_error(self, mock_client_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = RuntimeError("simulated API failure")
        mock_client_cls.return_value = mock_client

        with patch.object(gemini_client, "ENV_FILE", NONEXISTENT_ENV_FILE):
            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}):
                with self.assertRaises(GeminiClientError) as ctx:
                    generate_response("hello")

        self.assertIn("Gemini API call failed", str(ctx.exception))
        self.assertIn("simulated API failure", str(ctx.exception))

    @patch("gemini_client.genai.Client")
    def test_empty_response_raises_gemini_client_error(self, mock_client_cls: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.text = ""
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_client_cls.return_value = mock_client

        with patch.object(gemini_client, "ENV_FILE", NONEXISTENT_ENV_FILE):
            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}):
                with self.assertRaises(GeminiClientError) as ctx:
                    generate_response("hello")

        self.assertIn("empty response", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

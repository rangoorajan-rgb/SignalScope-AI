"""Minimal Gemini API client for SignalScope AI.

This is the first Gemini connection layer only: it loads the API key,
sends a prompt, and returns the response text. It does not read buyer
questions, write any output file, or perform scoring or extraction —
those remain future work.
"""

from __future__ import annotations

import os
from pathlib import Path

from google import genai

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = REPO_ROOT / ".env"
DEFAULT_MODEL = "gemini-2.5-flash"


class GeminiClientError(Exception):
    """Raised for problems configuring or calling the Gemini API."""


def _load_dotenv(path: Path = ENV_FILE) -> None:
    """Load KEY=VALUE pairs from a .env file into the process environment.

    Minimal, dependency-free loader (no python-dotenv package required).
    Never overrides a variable already set in the environment. Silently
    does nothing if the file does not exist.
    """
    if not path.is_file():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def generate_response(prompt: str, model: str = DEFAULT_MODEL) -> str:
    """Send a single prompt to Gemini and return the response text.

    Raises GeminiClientError if GEMINI_API_KEY is not set, or if the API
    call fails or returns no usable text.
    """
    _load_dotenv(ENV_FILE)
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise GeminiClientError(
            "GEMINI_API_KEY is not set. Create a .env file in the project "
            "root with GEMINI_API_KEY=<your key> (see .env.example)."
        )

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(model=model, contents=prompt)
    except Exception as exc:  # SDK/network/auth/quota errors, deliberately broad
        raise GeminiClientError(f"Gemini API call failed: {exc}") from exc

    text = getattr(response, "text", None)
    if not text:
        raise GeminiClientError("Gemini API returned an empty response.")

    return text

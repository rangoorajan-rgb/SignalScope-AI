"""Standalone Gemini connectivity check.

Sends one fixed prompt to Gemini and prints the response. Used only to
verify that GEMINI_API_KEY is configured correctly and the SDK can reach
the API — nothing else.
"""

from gemini_client import GeminiClientError, generate_response

PROMPT = "Reply with exactly: SignalScope AI connection successful."


def main() -> int:
    try:
        response = generate_response(PROMPT)
    except GeminiClientError as exc:
        print(f"Error: {exc}")
        return 1

    print(response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Tests for src/audit_runner.py."""

from __future__ import annotations

import csv
import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from audit_runner import AuditRunnerError, load_questions, main, print_questions  # noqa: E402

REAL_BOOTS_QUESTION_FILE = (
    REPO_ROOT / "audits" / "boots-uk-health-beauty" / "buyer_questions.csv"
)


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


class LoadQuestionsTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_loads_valid_file(self) -> None:
        csv_path = self.tmp_path / "buyer_questions.csv"
        write_csv(
            csv_path,
            fieldnames=["question_id", "buyer_journey_stage", "question", "intent", "notes"],
            rows=[
                {
                    "question_id": "PA01",
                    "buyer_journey_stage": "Problem Awareness",
                    "question": "What are the most common challenges?",
                    "intent": "Test intent",
                    "notes": "Test notes",
                },
                {
                    "question_id": "SD01",
                    "buyer_journey_stage": "Solution Discovery",
                    "question": "What are the best solutions?",
                    "intent": "Test intent",
                    "notes": "Test notes",
                },
            ],
        )

        rows = load_questions(str(csv_path))

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["question_id"], "PA01")
        self.assertEqual(rows[0]["buyer_journey_stage"], "Problem Awareness")
        self.assertEqual(rows[1]["question_id"], "SD01")

    def test_missing_file_raises(self) -> None:
        missing_path = self.tmp_path / "does_not_exist.csv"

        with self.assertRaises(AuditRunnerError) as ctx:
            load_questions(str(missing_path))

        self.assertIn("not found", str(ctx.exception))

    def test_missing_required_column_raises(self) -> None:
        csv_path = self.tmp_path / "buyer_questions.csv"
        # Missing "buyer_journey_stage".
        write_csv(
            csv_path,
            fieldnames=["question_id", "question"],
            rows=[{"question_id": "PA01", "question": "What are the challenges?"}],
        )

        with self.assertRaises(AuditRunnerError) as ctx:
            load_questions(str(csv_path))

        self.assertIn("buyer_journey_stage", str(ctx.exception))

    def test_missing_multiple_required_columns_raises(self) -> None:
        csv_path = self.tmp_path / "buyer_questions.csv"
        write_csv(csv_path, fieldnames=["intent", "notes"], rows=[])

        with self.assertRaises(AuditRunnerError) as ctx:
            load_questions(str(csv_path))

        message = str(ctx.exception)
        self.assertIn("question_id", message)
        self.assertIn("buyer_journey_stage", message)
        self.assertIn("question", message)

    def test_empty_question_file_raises(self) -> None:
        csv_path = self.tmp_path / "buyer_questions.csv"
        write_csv(
            csv_path,
            fieldnames=["question_id", "buyer_journey_stage", "question"],
            rows=[],
        )

        with self.assertRaises(AuditRunnerError) as ctx:
            load_questions(str(csv_path))

        self.assertIn("no question rows", str(ctx.exception))


class PrintQuestionsTests(unittest.TestCase):
    def test_output_format(self) -> None:
        rows = [
            {"question_id": "PA01", "buyer_journey_stage": "Problem Awareness", "question": "What are the challenges?"},
            {"question_id": "SD01", "buyer_journey_stage": "Solution Discovery", "question": "What are the options?"},
        ]

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            print_questions(rows)
        output = buffer.getvalue()

        self.assertIn("[PA01] Problem Awareness\nWhat are the challenges?\n", output)
        self.assertIn("[SD01] Solution Discovery\nWhat are the options?\n", output)
        self.assertIn("Total questions loaded: 2", output)
        self.assertTrue(output.strip().endswith("Total questions loaded: 2"))


class MainTests(unittest.TestCase):
    def test_main_reports_error_and_returns_1_for_missing_file(self) -> None:
        stderr_buffer = io.StringIO()
        with redirect_stderr(stderr_buffer):
            exit_code = main(["does/not/exist.csv"])

        self.assertEqual(exit_code, 1)
        self.assertIn("Error:", stderr_buffer.getvalue())
        self.assertIn("not found", stderr_buffer.getvalue())

    def test_main_returns_0_and_prints_questions_for_real_boots_file(self) -> None:
        self.assertTrue(
            REAL_BOOTS_QUESTION_FILE.is_file(),
            f"Expected fixture file at {REAL_BOOTS_QUESTION_FILE}",
        )

        stdout_buffer = io.StringIO()
        with redirect_stdout(stdout_buffer):
            exit_code = main([str(REAL_BOOTS_QUESTION_FILE)])
        output = stdout_buffer.getvalue()

        self.assertEqual(exit_code, 0)
        self.assertIn("[PA01] Problem Awareness", output)
        self.assertIn("Total questions loaded: 40", output)


class RealBootsQuestionFileTests(unittest.TestCase):
    """Integration check against the real Sprint 3 audit instance file."""

    def test_loads_all_40_boots_questions(self) -> None:
        self.assertTrue(
            REAL_BOOTS_QUESTION_FILE.is_file(),
            f"Expected fixture file at {REAL_BOOTS_QUESTION_FILE}",
        )

        rows = load_questions(str(REAL_BOOTS_QUESTION_FILE))

        self.assertEqual(len(rows), 40)
        self.assertEqual(rows[0]["question_id"], "PA01")
        self.assertEqual(rows[0]["buyer_journey_stage"], "Problem Awareness")
        self.assertEqual(rows[-1]["question_id"], "PD08")
        self.assertEqual(rows[-1]["buyer_journey_stage"], "Purchase Decision")


if __name__ == "__main__":
    unittest.main()

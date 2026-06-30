from __future__ import annotations

import unittest

from app.models import Annotation
from app.sleep_onset import build_spindle_sleep_onset_report


def annotation(
    annotation_id: str,
    start: float,
    end: float,
    status: str = "accepted",
) -> Annotation:
    return Annotation(
        id=annotation_id,
        file_id="recording-1",
        source="human",
        status=status,
        start_time_sec=start,
        end_time_sec=end,
        channels=["C3"],
        confidence=None,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )


class SleepOnsetReportTests(unittest.TestCase):
    def test_detects_first_consecutive_supported_pair(self) -> None:
        report = build_spindle_sleep_onset_report(
            subject_id="S01",
            duration_sec=180,
            annotations=[
                annotation("a", 65.0, 65.8),
                annotation("b", 95.0, 95.9),
                annotation("c", 125.0, 125.7),
            ],
        )

        self.assertTrue(report.detected)
        self.assertEqual(report.sleep_onset_epoch, 2)
        self.assertEqual(report.sleep_onset_time_sec, 60)
        self.assertEqual(report.supporting_epochs, [2, 3])
        self.assertEqual([item.candidate_id for item in report.supporting_spindles], ["a", "b"])

    def test_ignores_unaccepted_candidates(self) -> None:
        report = build_spindle_sleep_onset_report(
            subject_id="S02",
            duration_sec=120,
            annotations=[
                annotation("a", 35.0, 35.8, status="proposed"),
                annotation("b", 65.0, 65.8),
            ],
        )

        self.assertFalse(report.detected)
        self.assertEqual(report.epoch_summary[1].label, "not_N2_like")
        self.assertEqual(report.epoch_summary[2].label, "N2_like")

    def test_uses_epoch_start_not_spindle_start(self) -> None:
        report = build_spindle_sleep_onset_report(
            subject_id="S03",
            duration_sec=90,
            annotations=[
                annotation("a", 5.5, 6.3),
                annotation("b", 35.2, 36.0),
            ],
        )

        self.assertTrue(report.detected)
        self.assertEqual(report.sleep_onset_time_sec, 0)
        self.assertNotEqual(report.sleep_onset_time_sec, report.supporting_spindles[0].start_sec)


if __name__ == "__main__":
    unittest.main()

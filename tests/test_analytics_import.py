from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.report_short_experiment import load_metrics


class AnalyticsImportTest(unittest.TestCase):
    def test_rejects_invalid_manual_metrics(self) -> None:
        header = (
            "experiment_id,assignment_id,slot,variant,video_id,published_at,"
            "shown_in_feed,engaged_views,stayed_to_watch_pct,swiped_away_pct,"
            "avg_view_duration_seconds,avg_percentage_viewed,"
            "shorts_feed_share_pct,views,subscriber_change,measured_at\n"
        )
        valid = (
            "shorts-discovery-v1,a0,0,baseline_dialogue,v0,"
            "2026-07-26T03:00:00+00:00,100,30,30,70,12,80,90,50,1,"
            "2026-07-28T03:00:00+00:00\n"
        )
        invalid_rows = {
            "non-finite": valid.replace(",100,30,30,", ",nan,30,30,"),
            "percentage": valid.replace(",30,70,", ",101,70,"),
            "timezone": valid.replace("+00:00", "", 1),
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "metrics.csv"
            path.write_text(header + valid)
            self.assertEqual(len(load_metrics(path)), 1)
            for label, row in invalid_rows.items():
                with self.subTest(label=label):
                    path.write_text(header + row)
                    with self.assertRaises(ValueError):
                        load_metrics(path)


if __name__ == "__main__":
    unittest.main()

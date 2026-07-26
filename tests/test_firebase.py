from __future__ import annotations

import unittest
from unittest.mock import patch

from lib import firebase


class StoryPickEvidenceTest(unittest.TestCase):
    def test_preserves_proof_checkpoint_and_invalidation(self) -> None:
        anomaly = {
            "ticker": "RKLB",
            "name": "Rocket Lab",
            "day_change_pct": -8.7,
            "headline": "Contract win can't stop the slide yet",
            "catalyst": "Contract execution",
            "thesis": "Great business, terrible price action",
            "key_points": ["The $266M contract is its largest ever, but execution remains."],
            "visual_summary": {
                "catalyst_cards": [
                    {"event": "Contract execution", "window": "quarter"}
                ],
                "risk_cards": [{"trigger": "Break below $60"}],
            },
        }
        with (
            patch.object(firebase, "get_daily_anomalies", return_value=[anomaly]),
            patch.object(firebase, "get_reddit_buzz", return_value=[]),
        ):
            pick = firebase.best_story_picks("US", n=1)[0]

        self.assertEqual(pick["proof"], "The $266M contract is its largest ever")
        self.assertEqual(
            pick["checkpoint"],
            "Contract execution progress over the next quarter",
        )
        self.assertEqual(pick["invalidation"], "Break below $60")


if __name__ == "__main__":
    unittest.main()

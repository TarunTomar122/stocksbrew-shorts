from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from lib.storygen import dialogue_issues, experiment_issues, generate_script


class DialogueQualityTest(unittest.TestCase):
    def test_experiment_requires_exact_first_line_and_no_advice(self) -> None:
        pick = {
            "name": "Tesla",
            "change_pct": -14.5,
            "format_variant": "move_mechanism",
        }
        rejected = {
            "dialogue": [{"character": "rae2", "text": "This stock collapsed."}],
            "title": "Buy the dip",
        }
        accepted = {
            "dialogue": [
                {
                    "character": "rae2",
                    "text": "Tesla fell 14.5%, yet capex is still accelerating.",
                }
            ],
            "title": "Tesla's 14.5% Capex Contradiction",
            "description": "Tesla fell while capex accelerated. #stocks #shorts",
        }

        self.assertTrue(experiment_issues(rejected, pick))
        self.assertEqual(experiment_issues(accepted, pick), [])

    def test_baseline_metadata_rejects_investment_advice(self) -> None:
        pick = {"name": "Sandisk", "format_variant": "baseline_dialogue"}
        candidate = {
            "dialogue": [{"character": "rae", "text": "This is a buying opportunity."}],
            "title": "Sandisk Is a Buy",
            "description": "Buy the dip. #stocks #shorts",
        }

        self.assertIn("remove investment recommendations", experiment_issues(candidate, pick))

    def test_invalid_cached_script_is_not_reused(self) -> None:
        cached = json.dumps(
            {
                "dialogue": [
                    {"character": "rae2", "text": "Sandisk is a buying opportunity."},
                    {
                        "character": "rae",
                        "text": "The memory market is improving, so investors should buy the dip before revenue accelerates again.",
                    },
                ],
                "title": "Sandisk Is a Buy",
                "description": "Buy the dip. #stocks #shorts",
            }
        )
        with (
            patch("lib.storygen._read_cache", return_value=cached),
            patch("lib.storygen._client", side_effect=RuntimeError("regenerate")) as client,
            self.assertRaisesRegex(RuntimeError, "regenerate"),
        ):
            generate_script({"name": "Sandisk", "format_variant": "baseline_dialogue"})

        client.assert_called_once()

    def test_rejects_formulaic_dialogue(self) -> None:
        dialogue = [
            {"character": "rae2", "text": "Did Nvidia drop a secret sauce?"},
            {"character": "rae", "text": "You bet. Fiber demand is rising."},
            {"character": "rae2", "text": "So the demand could last?"},
            {"character": "rae", "text": "Exactly. We'll see."},
        ]

        self.assertTrue(dialogue_issues(dialogue))

    def test_accepts_uneven_conversation(self) -> None:
        dialogue = [
            {"character": "rae2", "text": "Why is Corning moving with AI stocks?"},
            {
                "character": "rae",
                "text": "Corning makes the fiber connecting AI servers. Nvidia's spending can become durable revenue if data-center demand keeps expanding.",
            },
            {"character": "rae2", "text": "So Corning sells the roads while chipmakers race the cars."},
            {"character": "rae", "text": "Now results must prove the traffic is paying tolls."},
        ]

        self.assertEqual(dialogue_issues(dialogue), [])


if __name__ == "__main__":
    unittest.main()

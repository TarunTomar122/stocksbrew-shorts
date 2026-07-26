from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from lib.storygen import (
    _format_pick,
    _system_prompt,
    dialogue_issues,
    experiment_issues,
    generate_script,
)


class DialogueQualityTest(unittest.TestCase):
    def test_experiment_prompt_has_one_duration_contract(self) -> None:
        prompt = _system_prompt({"format_variant": "move_mechanism"})

        self.assertIn("56-70 word", prompt)
        self.assertNotIn("35-60 word", prompt)
        self.assertNotIn("2-3 sentence explanation", prompt)
        self.assertNotIn("Screaming Buy", prompt)
        self.assertIn("one 8-12 word reaction", prompt)
        self.assertIn(
            "exactly four turns",
            _format_pick({"format_variant": "move_mechanism"}),
        )

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
                },
                {
                    "character": "rae",
                    "text": "Management cut near-term delivery targets while keeping the new factory budget unchanged through the next production cycle.",
                },
                {
                    "character": "rae2",
                    "text": "That tells investors the market is punishing execution risk before added capacity has any chance to improve automotive revenue.",
                },
                {
                    "character": "rae",
                    "text": "The next report must show margins stabilizing as spending converts into delivered vehicles, cash flow, and measurable factory output.",
                },
            ],
            "title": "Tesla's 14.5% Capex Contradiction",
            "description": "Tesla fell while capex accelerated. #stocks #shorts",
        }

        self.assertTrue(experiment_issues(rejected, pick))
        self.assertEqual(experiment_issues(accepted, pick), [])
        too_short = {**accepted, "dialogue": accepted["dialogue"][:1]}
        self.assertIn(
            "use 56-70 words to keep experiment durations comparable",
            " ".join(experiment_issues(too_short, pick)),
        )
        invented_number = {
            **accepted,
            "dialogue": [
                accepted["dialogue"][0],
                {
                    **accepted["dialogue"][1],
                    "text": accepted["dialogue"][1]["text"] + " Revenue is 30% recurring.",
                },
                *accepted["dialogue"][2:],
            ],
        }
        self.assertIn(
            "use the verified move percentage as the only number",
            experiment_issues(invented_number, pick),
        )

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

    def test_cached_result_does_not_validate_its_input_fields(self) -> None:
        pick = {"name": "Tesla", "change_pct": -14.5, "format_variant": "move_mechanism"}
        cached = json.dumps(
            {
                **pick,
                "format_instructions": "Never say buy, sell, or hold.",
                "dialogue": [
                    {"character": "rae2", "text": "Tesla fell 14.5%, yet capex is still accelerating."},
                    {"character": "rae", "text": "Management cut near-term delivery targets while keeping the new factory budget unchanged through the next production cycle."},
                    {"character": "rae2", "text": "That tells investors the market is punishing execution risk before added capacity has any chance to improve automotive revenue."},
                    {"character": "rae", "text": "The next report must show margins stabilizing as spending converts into delivered vehicles, cash flow, and measurable factory output."},
                ],
                "title": "Tesla's 14.5% Capex Contradiction",
                "description": "Tesla fell while capex accelerated. #stocks #shorts",
            }
        )
        with (
            patch("lib.storygen._read_cache", return_value=cached),
            patch("lib.storygen._client") as client,
        ):
            result = generate_script(pick)

        self.assertEqual(result["title"], "Tesla's 14.5% Capex Contradiction")
        client.assert_not_called()

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

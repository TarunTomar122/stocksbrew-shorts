from __future__ import annotations

import unittest

from lib.experiments import (
    EXPERIMENT_PLAN,
    assignment_id,
    build_components,
    format_settings,
    previous_publication_verified,
    rank_story_picks,
    summarize_metrics,
    validate_buffer_results,
)


class ExperimentPlanTest(unittest.TestCase):
    def test_plan_is_six_balanced_slots(self) -> None:
        self.assertEqual(len(EXPERIMENT_PLAN), 6)
        self.assertEqual(EXPERIMENT_PLAN.count("baseline_dialogue"), 3)
        self.assertEqual(len(set(EXPERIMENT_PLAN) - {"baseline_dialogue"}), 3)

    def test_assignment_id_is_stable(self) -> None:
        self.assertEqual(
            assignment_id("shorts-discovery-v1", 2, "topic-123"),
            assignment_id("shorts-discovery-v1", 2, "topic-123"),
        )

    def test_next_slot_waits_for_previous_publication(self) -> None:
        self.assertTrue(previous_publication_verified({}, 0))
        self.assertFalse(previous_publication_verified({}, 1))
        self.assertFalse(previous_publication_verified({"last_published_slot": None}, 1))
        self.assertTrue(previous_publication_verified({"last_published_slot": 0}, 1))

    def test_new_formats_put_proof_in_frame_one(self) -> None:
        pick = {
            "name": "Tesla",
            "change_pct": -14.5,
            "headline": "Margins collapsed despite record revenue",
            "catalyst": "Management guidance",
            "sector": "Consumer Discretionary",
        }

        for variant in set(EXPERIMENT_PLAN) - {"baseline_dialogue"}:
            components = build_components(pick, variant)
            self.assertEqual(components[0]["type"], "big_move")
            self.assertEqual(components[0]["show_at"], 0)
            self.assertIn("Margins collapsed", components[0]["data"]["contradiction"])
            self.assertLessEqual(format_settings(variant)["speaker_scale"], 0.32)


class StorySelectionTest(unittest.TestCase):
    def test_specific_hard_move_beats_vague_mover(self) -> None:
        picks = [
            {
                "ticker": "LMT",
                "name": "Lockheed Martin",
                "change_pct": 10.4,
                "headline": "Lockheed Martin is a top mover.",
                "catalyst": None,
                "thesis": "Quiet strength.",
            },
            {
                "ticker": "TSLA",
                "name": "Tesla",
                "change_pct": -14.5,
                "headline": "Margin collapse and capex shock crush Tesla",
                "catalyst": "Management guidance",
                "thesis": "Margins fell while spending jumped.",
            },
        ]

        ranked = rank_story_picks(picks, min_move_pct=5)

        self.assertEqual(ranked[0]["ticker"], "TSLA")
        self.assertGreater(ranked[0]["selection_score"], ranked[1]["selection_score"])


class PublicationTest(unittest.TestCase):
    def test_publication_requires_all_requested_services(self) -> None:
        with self.assertRaises(RuntimeError):
            validate_buffer_results(
                [{"service": "youtube", "status": "posted", "id": "yt-1"}],
                {"youtube", "instagram"},
            )

        validate_buffer_results(
            [
                {"service": "youtube", "status": "posted", "id": "yt-1"},
                {"service": "instagram", "status": "posted", "id": "ig-1"},
            ],
            {"youtube", "instagram"},
        )

        with self.assertRaises(RuntimeError):
            validate_buffer_results(
                [
                    {"service": "youtube", "status": "posted", "id": "yt-1"},
                    {"service": "youtube", "status": "error", "id": "yt-2"},
                    {"service": "instagram", "status": "posted", "id": "ig-1"},
                ],
                {"youtube", "instagram"},
            )


class AnalyticsReportTest(unittest.TestCase):
    def test_retention_gate_precedes_views(self) -> None:
        rows = [
            {
                "experiment_id": "shorts-discovery-v1",
                "assignment_id": "a0",
                "slot": 0,
                "variant": "baseline_dialogue",
                "stayed_to_watch_pct": 30,
                "avg_percentage_viewed": 80,
                "views": 2000,
            },
            {
                "experiment_id": "shorts-discovery-v1",
                "assignment_id": "a2",
                "slot": 2,
                "variant": "baseline_dialogue",
                "stayed_to_watch_pct": 31,
                "avg_percentage_viewed": 81,
                "views": 1800,
            },
            {
                "experiment_id": "shorts-discovery-v1",
                "assignment_id": "a4",
                "slot": 4,
                "variant": "baseline_dialogue",
                "stayed_to_watch_pct": 29,
                "avg_percentage_viewed": 79,
                "views": 2200,
            },
            {
                "experiment_id": "shorts-discovery-v1",
                "assignment_id": "a1",
                "slot": 1,
                "variant": "move_mechanism",
                "stayed_to_watch_pct": 38,
                "avg_percentage_viewed": 82,
                "views": 500,
            },
            {
                "experiment_id": "shorts-discovery-v1",
                "assignment_id": "a3",
                "slot": 3,
                "variant": "catalyst_checkpoint",
                "stayed_to_watch_pct": 37,
                "avg_percentage_viewed": 81,
                "views": 400,
            },
            {
                "experiment_id": "shorts-discovery-v1",
                "assignment_id": "a5",
                "slot": 5,
                "variant": "radar_invalidation",
                "stayed_to_watch_pct": 39,
                "avg_percentage_viewed": 83,
                "views": 600,
            },
        ]
        for row in rows:
            row["duration_seconds"] = 23

        summary = summarize_metrics(rows)

        self.assertTrue(summary["new_format_passes_retention_gate"])
        self.assertEqual(summary["baseline"]["views"], 2000)

        for row in rows:
            if row["variant"] != "baseline_dialogue":
                row["duration_seconds"] = 12
        self.assertEqual(summarize_metrics(rows)["gate"], "incomparable_duration")

    def test_gate_waits_for_all_six_videos(self) -> None:
        summary = summarize_metrics(
            [{
                "experiment_id": "shorts-discovery-v1",
                "variant": "baseline_dialogue",
                "stayed_to_watch_pct": 30,
                "avg_percentage_viewed": 80,
            }]
        )

        self.assertEqual(summary["gate"], "incomplete_experiment")


if __name__ == "__main__":
    unittest.main()

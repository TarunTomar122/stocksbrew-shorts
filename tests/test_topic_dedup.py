from __future__ import annotations

import unittest

from lib.topic_dedup import dedupe_items, is_near_duplicate, topic_fingerprint


class TopicDedupTest(unittest.TestCase):
    def test_same_story_fields_hash_to_same_topic(self) -> None:
        a = {
            "ticker": "NVDA",
            "name": "Nvidia",
            "headline": "Stock popped after a monster AI order",
            "catalyst": "AI demand",
            "source": "anomaly",
        }
        b = {
            "ticker": "nvda",
            "name": " nvidia ",
            "headline": " stock popped after a monster ai order ",
            "catalyst": "AI demand",
            "source": "anomaly",
        }

        self.assertEqual(topic_fingerprint(a), topic_fingerprint(b))

    def test_dedupe_items_drops_repeated_topics(self) -> None:
        picks = [
            {
                "ticker": "NVDA",
                "name": "Nvidia",
                "headline": "AI demand keeps ripping",
                "source": "anomaly",
            },
            {
                "ticker": "NVDA",
                "name": "Nvidia",
                "headline": "AI demand keeps ripping",
                "source": "anomaly",
            },
        ]

        fresh = dedupe_items(picks, blocked_keys=set())

        self.assertEqual(len(fresh), 1)
        self.assertIn("topic_key", fresh[0])

    def test_near_duplicate_ticker_angles_are_blocked(self) -> None:
        candidate = {
            "ticker": "OUST",
            "headline": "Ouster drops after hitting a 52 week high",
            "catalyst": "Momentum reversal",
        }
        history = [{
            "ticker": "OUST",
            "headline": "Ouster dipped from its 52-week high",
            "catalyst": "Momentum reversed",
        }]

        self.assertTrue(is_near_duplicate(candidate, history))


if __name__ == "__main__":
    unittest.main()

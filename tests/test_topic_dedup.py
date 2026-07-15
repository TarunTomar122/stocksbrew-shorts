from __future__ import annotations

import unittest

from lib.topic_dedup import dedupe_items, topic_fingerprint


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


if __name__ == "__main__":
    unittest.main()

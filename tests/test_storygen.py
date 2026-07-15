from __future__ import annotations

import unittest

from lib.storygen import dialogue_issues


class DialogueQualityTest(unittest.TestCase):
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

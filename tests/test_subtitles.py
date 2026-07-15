from __future__ import annotations

import unittest

from lib import subtitles, transcribe


class SubtitleNumbersTest(unittest.TestCase):
    def test_merges_whisper_number_fragments(self) -> None:
        words = [
            {"word": "11", "start": 1.26, "end": 1.70},
            {"word": ".1", "start": 1.70, "end": 2.22},
            {"word": "%?", "start": 2.22, "end": 2.66},
            {"word": "Must", "start": 2.92, "end": 3.06},
        ]

        self.assertEqual(
            transcribe.merge_numeric_fragments(words),
            [
                {"word": "11.1%?", "start": 1.26, "end": 2.66},
                {"word": "Must", "start": 2.92, "end": 3.06},
            ],
        )

    def test_drawtext_renders_percent_signs_literally(self) -> None:
        chain = subtitles.build_chain(
            [{"word": "11.1%", "start": 0.0, "end": 1.0}],
            top_margin=100,
            last_label="base",
        )

        self.assertIn("text='11.1%'", chain)
        self.assertIn("expansion=none", chain)


if __name__ == "__main__":
    unittest.main()

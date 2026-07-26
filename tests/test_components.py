from __future__ import annotations

import unittest

from PIL import Image

from lib.components import render_component


class ExperimentComponentTest(unittest.TestCase):
    def test_signature_card_markers_are_visible(self) -> None:
        for component_type in (
            "mechanism_card",
            "checkpoint_card",
            "invalidation_card",
        ):
            with self.subTest(component_type=component_type):
                path = render_component(
                    {"type": component_type, "data": {"text": "One concrete claim"}}
                )
                self.assertIsNotNone(path)
                try:
                    with Image.open(path) as image:
                        badge = image.crop((55, 65, 230, image.height - 25))
                        self.assertTrue(
                            any(
                                pixel[:3] == (255, 255, 255)
                                for pixel in badge.get_flattened_data()
                            )
                        )
                finally:
                    path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()

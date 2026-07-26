from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import runner


class RunnerFailureTest(unittest.TestCase):
    def test_pipeline_failure_moves_script_and_exits_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            queue = root / "queue"
            done = root / "done"
            failed = root / "failed"
            output = root / "output"
            cache = root / "cache"
            for folder in (queue, done, failed, output, cache):
                folder.mkdir()
            script = queue / "test.json"
            script.write_text(json.dumps({"text": "test"}))

            with (
                patch.object(runner, "QUEUE", queue),
                patch.object(runner, "DONE", done),
                patch.object(runner, "FAILED", failed),
                patch.object(runner, "OUTPUT", output),
                patch.object(runner, "TRANSCRIPT_CACHE", cache),
                patch.object(
                    runner, "process_script", side_effect=RuntimeError("Buffer failed")
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "Buffer failed"):
                    runner.run_queue(paths=[script])

            self.assertTrue((failed / "test.json").exists())
            self.assertFalse((done / "test.json").exists())

    def test_partial_buffer_results_are_persisted_before_failure(self) -> None:
        from lib import avatar, brainrot, buffer, catalog, firebase, hosting, transcribe

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "short.mp4"
            line = SimpleNamespace(
                character="rae2", text="Test line.", start_time=0, end_time=1
            )
            dialogue = SimpleNamespace(
                video_path=root / "avatar.mp4", duration=1, lines=[line]
            )
            results = [
                {"service": "youtube", "status": "posted"},
                {"service": "instagram", "status": "error"},
            ]

            with (
                patch.object(avatar, "generate_dialogue", return_value=dialogue),
                patch.object(transcribe, "transcribe_with_cache", return_value=[]),
                patch.object(catalog, "pick", return_value={"id": "bg"}),
                patch.object(catalog, "resolve_path", return_value=root / "bg.mp4"),
                patch.object(
                    brainrot,
                    "build",
                    side_effect=lambda **kwargs: kwargs["output"].write_bytes(b"video"),
                ),
                patch.object(hosting, "upload_video", return_value="https://video"),
                patch.object(
                    buffer, "schedule_to_youtube_and_instagram", return_value=results
                ),
                patch.object(firebase, "set_experiment_assignment_status"),
                patch.object(firebase, "begin_scheduling", return_value="scheduling"),
                patch.object(firebase, "record_scheduling_results") as record,
                patch.object(firebase, "mark_publication_uncertain", return_value=True),
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "Publishing not confirmed for: instagram"
                ):
                    runner.process_script(
                        {
                            "id": "assignment",
                            "assignment_id": "assignment",
                            "dialogue": [{"character": "rae2", "text": "Test line."}],
                            "output": str(output),
                            "topic_key": "topic",
                            "title": "Title",
                            "description": "Description",
                        }
                    )

            record.assert_called_once_with("topic", results)


if __name__ == "__main__":
    unittest.main()

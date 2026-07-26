from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()

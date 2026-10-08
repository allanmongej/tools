"""Real FFmpeg boundary checks: no mocked decoder and no model download."""

import contextlib
import io
import json
import tempfile
import unittest
import wave
from pathlib import Path

from agent_tools.cli import main


class MediaTest(unittest.TestCase):
    def assert_media_error(self, source, code, directory):
        stdout, stderr = io.StringIO(), io.StringIO()
        destination = directory / "result.json"
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = main(["transcribe", str(source), "--output", str(destination)])
        self.assertEqual(status, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(json.loads(stderr.getvalue())["error"]["code"], code)
        self.assertFalse(destination.exists())
        self.assertEqual(list(directory.glob(".tools-*.tmp")), [])

    def test_corrupt_media_fails_with_real_decoder(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            source = directory / "bad.wav"
            source.write_text("This is not an audio file.")
            self.assert_media_error(source, "invalid_media", directory)

    def test_silent_audio_does_not_produce_an_invented_transcript(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            source = directory / "silence.wav"
            with wave.open(str(source), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(16000)
                audio.writeframes(b"\x00\x00" * 16000)
            self.assert_media_error(source, "no_audio", directory)


if __name__ == "__main__":
    unittest.main()

"""Full inspection with real FFmpeg; only speech inference/network are isolated."""

import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import imageio_ffmpeg

from agent_tools.cli import ToolError, main
from test_cli import TRANSCRIPTION


class InspectTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_directory = tempfile.TemporaryDirectory()
        cls.silent_video = Path(cls.fixture_directory.name) / "silent scenes.mp4"
        cls.video = Path(cls.fixture_directory.name) / "two scenes.mp4"
        # A real, silent video: the red-to-blue cut is exactly at two seconds.
        subprocess.run([
            imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=red:size=160x240:rate=10:duration=2",
            "-f", "lavfi", "-i", "color=blue:size=160x240:rate=10:duration=2",
            "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(cls.silent_video),
        ], check=True, capture_output=True)
        subprocess.run([
            imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-hide_banner", "-loglevel", "error",
            "-i", str(cls.silent_video), "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
            "-c:v", "copy", "-c:a", "aac", "-shortest", str(cls.video),
        ], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.fixture_directory.cleanup()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.destination = self.root / "inspection"

    def invoke(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(list(args))
        return code, stdout.getvalue(), stderr.getvalue()

    @patch("agent_tools.cli.transcribe_media", return_value=TRANSCRIPTION)
    def test_full_inspection_saves_real_visual_evidence_and_manifest(self, inference):
        code, stdout, stderr = self.invoke("inspect", str(self.video), "--output-dir", str(self.destination))
        self.assertEqual(code, 0, stderr)
        result = json.loads(stdout)
        self.assertEqual(json.loads((self.destination / "inspection.json").read_text()), result)
        self.assertEqual(result["transcription"]["text"], TRANSCRIPTION["text"])
        self.assertEqual(result["source"]["path"], str(self.video.resolve()))
        visual = result["visual"]
        self.assertAlmostEqual(visual["duration_seconds"], 4.0, places=1)
        self.assertEqual((visual["width"], visual["height"]), (160, 240))
        self.assertTrue(any(abs(time - 2.0) < 0.11 for time in visual["scene_candidates"]))
        self.assertGreaterEqual(len(visual["frames"]), 2)
        for frame in visual["frames"]:
            self.assertTrue(0 <= frame["time"] < 4.0)
            self.assertTrue(Path(frame["path"]).read_bytes().startswith(b"\xff\xd8"))
        # Decode actual images: timestamped evidence must show the right scene.
        def pixel(path):
            return subprocess.run([
                imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-hide_banner", "-loglevel", "error",
                "-i", path, "-vf", "scale=1:1", "-frames:v", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "-",
            ], check=True, capture_output=True).stdout
        first, last = pixel(visual["frames"][0]["path"]), pixel(visual["frames"][-1]["path"])
        self.assertGreater(first[0], 200)
        self.assertLess(first[2], 40)
        self.assertGreater(last[2], 200)
        self.assertLess(last[0], 40)
        self.assertTrue(Path(visual["contact_sheet"]).is_file())
        self.assertEqual(Path(visual["video_path"]).read_bytes(), self.video.read_bytes())
        self.assertTrue(visual["sequences"])
        for sequence in visual["sequences"]:
            self.assertLess(sequence["start"], sequence["end"])
            self.assertLessEqual(sequence["end"], 4.0)
            self.assertTrue(Path(sequence["clip_path"]).is_file())
            self.assertTrue(Path(sequence["strip_path"]).read_bytes().startswith(b"\xff\xd8"))
            self.assertEqual(len(sequence["frame_times"]), 4)
        self.assertEqual(sorted(path.name for path in self.root.iterdir()), ["inspection"])

    @patch("agent_tools.cli.transcribe_media")
    def test_existing_directory_preserved_before_processing(self, inference):
        self.destination.mkdir()
        draft = self.destination / "draft.md"
        draft.write_text("mi idea manual")
        code, stdout, stderr = self.invoke("inspect", str(self.video), "--output-dir", str(self.destination))
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(json.loads(stderr.splitlines()[-1])["error"]["code"], "output_exists")
        self.assertEqual(draft.read_text(), "mi idea manual")
        inference.assert_not_called()

    @patch("agent_tools.cli.transcribe_media")
    def test_destination_created_during_work_preserved(self, inference):
        def recognize(*args, **kwargs):
            self.destination.mkdir()
            (self.destination / "draft.md").write_text("idea creada mientras trabajabas")
            return TRANSCRIPTION
        inference.side_effect = recognize
        code, stdout, stderr = self.invoke("inspect", str(self.video), "--output-dir", str(self.destination))
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(json.loads(stderr.splitlines()[-1])["error"]["code"], "output_exists")
        self.assertEqual((self.destination / "draft.md").read_text(), "idea creada mientras trabajabas")
        self.assertEqual(sorted(path.name for path in self.root.iterdir()), ["inspection"])

    @patch("agent_tools.cli.transcribe_media")
    def test_silent_video_keeps_visuals_without_inventing_words(self, inference):
        code, stdout, stderr = self.invoke("inspect", str(self.silent_video), "--output-dir", str(self.destination))
        self.assertEqual(code, 0, stderr)
        result = json.loads(stdout)
        self.assertEqual(result["transcription"]["status"], "no_audio")
        self.assertEqual(result["transcription"]["text"], "")
        self.assertEqual(result["transcription"]["segments"], [])
        self.assertTrue(result["visual"]["frames"])
        inference.assert_not_called()

    @patch("agent_tools.cli.transcribe_media")
    def test_audio_only_is_rejected_without_partial_artifacts(self, inference):
        audio = self.root / "audio.wav"
        with wave.open(str(audio), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(16000)
            handle.writeframes(b"\x00\x00" * 16000)
        code, stdout, stderr = self.invoke("inspect", str(audio), "--output-dir", str(self.destination))
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(json.loads(stderr)["error"]["code"], "no_video")
        self.assertEqual(list(self.root.iterdir()), [audio])
        inference.assert_not_called()

    @patch("agent_tools.cli.transcribe_media", side_effect=ToolError("transcription_failed", "Modelo no disponible."))
    def test_failed_inference_cleans_staged_visuals_without_publishing(self, inference):
        code, stdout, stderr = self.invoke("inspect", str(self.video), "--output-dir", str(self.destination))
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(json.loads(stderr.splitlines()[-1])["error"]["code"], "transcription_failed")
        self.assertEqual(list(self.root.iterdir()), [])

    @patch("agent_tools.cli.transcribe_media", return_value={**TRANSCRIPTION, "text": "", "segments": []})
    def test_no_speech_still_returns_visual_reference(self, inference):
        code, stdout, stderr = self.invoke("inspect", str(self.video), "--output-dir", str(self.destination))
        self.assertEqual(code, 0, stderr)
        result = json.loads(stdout)
        self.assertEqual(result["transcription"]["status"], "no_speech")
        self.assertEqual(result["transcription"]["text"], "")
        self.assertTrue(Path(result["visual"]["video_path"]).is_file())

    @patch("agent_tools.cli.transcribe_media", return_value=TRANSCRIPTION)
    def test_partial_save_rolls_back_only_own_files_and_preserves_manual_work(self, inference):
        real_link = os.link
        count = 0
        def save(source, target):
            nonlocal count
            count += 1
            if count == 3:
                (self.destination / "draft.md").write_text("borrador de otro agente")
                raise OSError("disk full")
            real_link(source, target)
        with patch("agent_tools.cli.os.link", side_effect=save):
            code, stdout, stderr = self.invoke("inspect", str(self.video), "--output-dir", str(self.destination))
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(json.loads(stderr.splitlines()[-1])["error"]["code"], "output_unwritable")
        self.assertEqual(sorted(path.name for path in self.destination.iterdir()), ["draft.md"])
        self.assertEqual((self.destination / "draft.md").read_text(), "borrador de otro agente")
        self.assertEqual(sorted(path.name for path in self.root.iterdir()), ["inspection"])

    @patch("agent_tools.cli.download_media")
    @patch("agent_tools.cli.transcribe_media", return_value=TRANSCRIPTION)
    def test_url_requests_video_and_keeps_it_after_download_cleanup(self, inference, download):
        temporary_paths = []
        def obtain(url, directory, cookies, *, video=False):
            self.assertTrue(video, "Full inspection must not request bestaudio")
            temporary_paths.append(directory)
            media = directory / "media.mp4"
            media.write_bytes(self.video.read_bytes())
            return media, {"kind": "url", "url": url, "creator": "Autora"}
        download.side_effect = obtain
        url = "https://www.instagram.com/reel/example/"
        code, stdout, stderr = self.invoke("inspect", url, "--output-dir", str(self.destination))
        self.assertEqual(code, 0, stderr)
        result = json.loads(stdout)
        self.assertEqual(result["source"]["url"], url)
        self.assertEqual(result["source"]["creator"], "Autora")
        self.assertTrue(Path(result["visual"]["video_path"]).is_file())
        self.assertTrue(all(not path.exists() for path in temporary_paths))


if __name__ == "__main__":
    unittest.main()

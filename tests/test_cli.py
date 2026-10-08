"""Behavioral proof for the CLI contract; speech recognition is proven live separately."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_tools.cli import ToolError, main


TRANSCRIPTION = {
    "engine": "openai-whisper",
    "model": "small",
    "language": "es",
    "duration_seconds": 4.0,
    "text": "Hoy tengo tres pedidos pendientes.",
    "segments": [{"start": 0.0, "end": 4.0, "text": "Hoy tengo tres pedidos pendientes."}],
}


class CLITest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.media = self.root / "mi video.wav"
        self.media.write_bytes(b"test media; the inference boundary is mocked")

    def invoke(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(list(args))
        return code, stdout.getvalue(), stderr.getvalue()

    @patch("agent_tools.cli.transcribe_media", return_value=TRANSCRIPTION)
    def test_local_file_produces_json_with_source_and_saves_to_requested_path(self, inference):
        destination = self.root / "ideas" / "referencia.json"
        code, stdout, stderr = self.invoke("transcribe", str(self.media), "--output", str(destination))
        self.assertEqual(code, 0, stderr)
        result = json.loads(stdout)
        self.assertEqual(result["source"]["kind"], "file")
        self.assertEqual(result["source"]["path"], str(self.media.resolve()))
        self.assertEqual(result["transcription"]["text"], TRANSCRIPTION["text"])
        self.assertEqual(json.loads(destination.read_text()), result)
        inference.assert_called_once()

    @patch("agent_tools.cli.transcribe_media", return_value=TRANSCRIPTION)
    def test_existing_destination_is_preserved_before_inference(self, inference):
        destination = self.root / "idea.json"
        destination.write_text("mi borrador manual")
        code, stdout, stderr = self.invoke("transcribe", str(self.media), "--output", str(destination))
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(json.loads(stderr)["error"]["code"], "output_exists")
        self.assertEqual(destination.read_text(), "mi borrador manual")
        inference.assert_not_called()

    @patch("agent_tools.cli.transcribe_media", return_value=TRANSCRIPTION)
    def test_missing_input_does_not_create_output(self, inference):
        destination = self.root / "result.json"
        code, stdout, stderr = self.invoke("transcribe", str(self.root / "missing.mp4"), "--output", str(destination))
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(json.loads(stderr)["error"]["code"], "input_not_found")
        self.assertFalse(destination.exists())
        inference.assert_not_called()

    @patch("agent_tools.cli.transcribe_media", return_value=TRANSCRIPTION)
    def test_invalid_output_parent_fails_before_inference(self, inference):
        parent = self.root / "not-a-directory"
        parent.write_text("preserve me")
        code, stdout, stderr = self.invoke("transcribe", str(self.media), "--output", str(parent / "result.json"))
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(json.loads(stderr)["error"]["code"], "output_unwritable")
        self.assertEqual(parent.read_text(), "preserve me")
        inference.assert_not_called()

    @patch("agent_tools.cli.transcribe_media", return_value={**TRANSCRIPTION, "text": "  ", "segments": []})
    def test_no_speech_is_an_error_and_is_not_saved(self, inference):
        destination = self.root / "result.json"
        code, stdout, stderr = self.invoke("transcribe", str(self.media), "--output", str(destination))
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(json.loads(stderr)["error"]["code"], "no_speech")
        self.assertFalse(destination.exists())

    @patch("agent_tools.cli.transcribe_media", side_effect=ToolError("invalid_media", "No se pudo leer el audio."))
    def test_inference_failure_is_json_on_stderr_without_a_partial_output(self, inference):
        destination = self.root / "result.json"
        code, stdout, stderr = self.invoke("transcribe", str(self.media), "--output", str(destination))
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(json.loads(stderr)["error"]["code"], "invalid_media")
        self.assertFalse(destination.exists())

    @patch("agent_tools.cli.transcribe_media")
    def test_library_stdout_is_redirected_and_unspecified_output_saves_nothing(self, inference):
        def recognize(*args, **kwargs):
            print("library progress")
            return TRANSCRIPTION
        inference.side_effect = recognize
        code, stdout, stderr = self.invoke("transcribe", str(self.media))
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)["transcription"]["language"], "es")
        self.assertIn("library progress", stderr)
        self.assertEqual(list(self.root.iterdir()), [self.media])

    @patch("agent_tools.cli.download_media", side_effect=ToolError("download_failed", "Instagram no permitió la descarga."))
    @patch("agent_tools.cli.transcribe_media", return_value=TRANSCRIPTION)
    def test_download_failure_never_runs_inference_or_saves_a_result(self, inference, download):
        destination = self.root / "result.json"
        code, stdout, stderr = self.invoke("transcribe", "https://www.instagram.com/reel/example/", "--output", str(destination))
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(json.loads(stderr)["error"]["code"], "download_failed")
        self.assertFalse(destination.exists())
        inference.assert_not_called()

    @patch("agent_tools.cli.download_media")
    @patch("agent_tools.cli.transcribe_media", return_value=TRANSCRIPTION)
    def test_url_retains_attribution_and_cleans_downloaded_media(self, inference, download):
        temporary_paths = []
        def obtain(url, directory, cookies):
            temporary_paths.append(directory)
            media = directory / "media.mp4"
            media.write_bytes(b"downloaded media")
            return media, {"kind": "url", "url": url, "provider": "Instagram", "id": "example", "title": "Referencia", "creator": "Autora"}
        download.side_effect = obtain
        url = "https://www.instagram.com/reel/example/"
        code, stdout, stderr = self.invoke("transcribe", url)
        self.assertEqual(code, 0, stderr)
        result = json.loads(stdout)
        self.assertEqual(result["source"]["url"], url)
        self.assertEqual(result["source"]["creator"], "Autora")
        self.assertTrue(temporary_paths)
        self.assertTrue(all(not path.exists() for path in temporary_paths))

    @patch("agent_tools.cli.download_media")
    @patch("agent_tools.cli.transcribe_media")
    def test_non_http_uri_is_rejected(self, inference, download):
        code, stdout, stderr = self.invoke("transcribe", "ftp://example.com/video.mp4")
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(json.loads(stderr)["error"]["code"], "invalid_input")
        download.assert_not_called()
        inference.assert_not_called()

    @patch("agent_tools.cli.download_media", side_effect=ToolError("download_failed", "Proveedor no disponible."))
    def test_long_url_is_not_treated_as_a_filesystem_path(self, download):
        url = "https://www.instagram.com/reel/example/?tracking=" + "x" * 2000
        code, stdout, stderr = self.invoke("transcribe", url)
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(json.loads(stderr)["error"]["code"], "download_failed")
        self.assertEqual(download.call_args.args[0], url)

    @patch("agent_tools.cli.transcribe_media")
    def test_destination_created_during_inference_is_preserved(self, inference):
        destination = self.root / "idea.json"
        def recognize(*args, **kwargs):
            destination.write_text("borrador creado mientras transcribías")
            return TRANSCRIPTION
        inference.side_effect = recognize
        code, stdout, stderr = self.invoke("transcribe", str(self.media), "--output", str(destination))
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(json.loads(stderr)["error"]["code"], "output_exists")
        self.assertEqual(destination.read_text(), "borrador creado mientras transcribías")
        self.assertEqual(sorted(path.name for path in self.root.iterdir()), ["idea.json", "mi video.wav"])


if __name__ == "__main__":
    unittest.main()

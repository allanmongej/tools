"""Transcribe or prepare a complete media reference. Stdout is the result contract."""

import argparse
import contextlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .errors import ToolError
from .visual import ffmpeg_executable, inspect_media, video_metadata


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ToolError("invalid_arguments", message)


def parser():
    command = Parser(description="Herramientas locales para agentes.")
    command.add_argument("--version", action="version", version="tools 0.1.0")
    commands = command.add_subparsers(dest="command", required=True, parser_class=Parser)
    transcribe = commands.add_parser("transcribe", help="Transcribe un enlace o archivo con Whisper local.")
    transcribe.add_argument("--output", type=Path, help="Guarda el JSON en esta ruta sin sobrescribir archivos.")
    inspect = commands.add_parser("inspect", help="Prepara transcripción, fotogramas y secuencias de un video.")
    inspect.add_argument("--output-dir", required=True, type=Path, help="Carpeta nueva para el video, imágenes, clips y JSON.")
    for subcommand in (transcribe, inspect):
        subcommand.add_argument("source", help="URL HTTP(S) o ruta de un archivo local.")
        subcommand.add_argument("--model", choices=("tiny", "base", "small", "medium", "large", "turbo"), default="small")
        subcommand.add_argument("--language", help="Código del idioma, por ejemplo es o en. Por defecto se detecta.")
        subcommand.add_argument("--cookies", type=Path, help="Archivo de cookies de una sesión autorizada para yt-dlp.")
    return command


def identify_source(value):
    try:
        url = urlsplit(value)
    except ValueError as error:
        raise ToolError("invalid_input", "El enlace no es válido.") from error
    if url.scheme in ("http", "https") and url.hostname:
        return "url", value
    if url.scheme:
        raise ToolError("invalid_input", "Utiliza un enlace HTTP(S) o un archivo local.")
    path = Path(value).expanduser()
    try:
        if path.is_file():
            return "file", path.resolve()
    except OSError as error:
        raise ToolError("invalid_input", "No se pudo leer la ruta indicada.") from error
    raise ToolError("input_not_found", f"No existe el archivo: {path}")


@contextlib.contextmanager
def output_destination(destination):
    """Check write access early; publish atomically without replacing another file."""
    if destination is None:
        yield None, None
        return
    destination = destination.expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise ToolError("output_exists", f"El destino ya existe: {destination}")
    temporary = None
    try:
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".tools-", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
        except OSError as error:
            raise ToolError("output_unwritable", f"No se puede escribir en el destino: {destination}") from error
        yield destination, temporary
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class DownloadLogger:
    def debug(self, message):
        pass

    def warning(self, message):
        print(f"[yt-dlp] {message}", file=sys.stderr)

    def error(self, message):
        # yt-dlp raises DownloadError; main emits the structured error once.
        pass


def download_media(url, directory, cookies, *, video=False):
    try:
        import yt_dlp
    except ImportError as error:
        raise ToolError("missing_dependency", "Instala las dependencias del proyecto con pip install -e .") from error
    options = {
        "format": "bestaudio/best",
        "outtmpl": str(directory / "media.%(ext)s"),
        "noplaylist": True,
        "playlist_items": "1",
        "quiet": True,
        "noprogress": True,
        "nocolor": True,
        "socket_timeout": 30,
        "retries": 2,
        "extractor_retries": 2,
        "logger": DownloadLogger(),
    }
    if video:
        options["format"] = "bv*+ba/b/bv"
        options["ffmpeg_location"] = ffmpeg_executable()
    if cookies is not None:
        options["cookiefile"] = str(cookies)
    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=True)
            if not info:
                raise ToolError("download_failed", "El proveedor no devolvió un video.")
            if info.get("_type") in ("playlist", "multi_video"):
                raise ToolError("unsupported_playlist", "Comparte el enlace a un solo video, no a una colección.")
            path = Path(downloader.prepare_filename(info))
    except yt_dlp.utils.DownloadError as error:
        raise ToolError("download_failed", f"No se pudo descargar el video: {error}. También puedes usar un archivo local.") from error
    if not path.is_file():
        raise ToolError("download_failed", "La descarga no produjo un archivo de audio o video.")
    source = {
        "kind": "url",
        "url": info.get("webpage_url") or url,
        "provider": info.get("extractor_key") or info.get("extractor"),
        "id": info.get("id"),
        "title": info.get("title"),
        "creator": info.get("uploader") or info.get("creator"),
        "description": info.get("description"),
    }
    return path, source


def transcribe_media(path, model_name, language):
    try:
        import numpy as np
        import whisper
    except ImportError as error:
        raise ToolError("missing_dependency", "Instala las dependencias del proyecto con pip install -e .") from error
    ffmpeg = ffmpeg_executable()
    try:
        decoded = subprocess.run(
            [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-threads", "1", "-i", str(path),
             "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "pipe:1"],
            capture_output=True, timeout=300, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ToolError("audio_decode_failed", "No se pudo ejecutar la conversión de audio con FFmpeg.") from error
    if decoded.returncode:
        detail = decoded.stderr.decode("utf-8", errors="replace").strip()[-500:]
        raise ToolError("invalid_media", f"No se pudo leer el audio: {detail}")
    audio = np.frombuffer(decoded.stdout, dtype=np.float32).copy()
    if not audio.size or not np.any(audio):
        raise ToolError("no_audio", "El archivo no contiene audio utilizable.")
    try:
        model = whisper.load_model(model_name, device="cpu")
        result = model.transcribe(audio, language=language, fp16=False, verbose=None)
    except (RuntimeError, ValueError, OSError) as error:
        raise ToolError("transcription_failed", f"Whisper no pudo completar la transcripción: {error}") from error
    return {
        "engine": "openai-whisper",
        "model": model_name,
        "language": result["language"],
        "duration_seconds": round(len(audio) / 16000, 3),
        "text": result["text"].strip(),
        "segments": [
            {"start": round(float(segment["start"]), 3), "end": round(float(segment["end"]), 3), "text": segment["text"].strip()}
            for segment in result["segments"]
        ],
    }


def run(args):
    kind, source_value = identify_source(args.source)
    cookies = args.cookies.expanduser().resolve() if args.cookies else None
    if cookies is not None and not cookies.is_file():
        raise ToolError("cookies_not_found", "No existe el archivo de cookies indicado.")
    if args.command == "inspect":
        return run_inspect(args, kind, source_value, cookies)
    with output_destination(args.output) as (destination, temporary_output):
        with tempfile.TemporaryDirectory(prefix="agent-tools-") as directory:
            if kind == "url":
                media, source = download_media(source_value, Path(directory), cookies)
            else:
                media = source_value
                source = {"kind": "file", "path": str(media), "title": media.name}
            transcription = transcribe_media(media, args.model, args.language)
        if not transcription["text"].strip():
            raise ToolError("no_speech", "Whisper no detectó palabras. Revisa si el video contiene voz.")
        result = {
            "schema_version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "transcription": transcription,
        }
        serialized = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if destination is not None:
            try:
                temporary_output.write_text(serialized, encoding="utf-8")
                os.link(temporary_output, destination)
            except FileExistsError as error:
                raise ToolError("output_exists", f"El destino ya existe: {destination}") from error
            except OSError as error:
                raise ToolError("output_unwritable", f"No se pudo guardar el resultado: {destination}") from error
        return serialized


def publish_inspection(stage, destination):
    """Reserve a new directory and link complete files without replacing drafts."""
    linked = []
    created = False
    try:
        destination.mkdir()
        created = True
        # The manifest becomes visible only after all its referenced assets exist.
        for source in sorted(stage.iterdir(), key=lambda path: (path.name == "inspection.json", path.name)):
            target = destination / source.name
            os.link(source, target)
            linked.append((source, target))
    except BaseException as error:
        # Roll back only our own links; never remove files inserted by another writer.
        for source, target in linked:
            try:
                if not target.is_symlink() and target.samefile(source):
                    target.unlink()
            except OSError:
                pass
        if created:
            try:
                destination.rmdir()
            except OSError:
                pass
        if isinstance(error, FileExistsError):
            raise ToolError("output_exists", f"El destino ya existe: {destination}") from error
        if isinstance(error, OSError):
            raise ToolError("output_unwritable", f"No se pudo guardar la inspección: {destination}") from error
        raise


def run_inspect(args, kind, source_value, cookies):
    destination = args.output_dir.expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise ToolError("output_exists", f"El destino ya existe: {destination}")
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = tempfile.TemporaryDirectory(prefix=".tools-inspect-", dir=destination.parent)
    except OSError as error:
        raise ToolError("output_unwritable", f"No se puede escribir en el destino: {destination}") from error
    with staging as directory, tempfile.TemporaryDirectory(prefix="agent-tools-") as downloads:
        stage = Path(directory)
        if kind == "url":
            media, source = download_media(source_value, Path(downloads), cookies, video=True)
        else:
            media = source_value
            source = {"kind": "file", "path": str(media), "title": media.name}
        metadata = video_metadata(media)
        print("[inspect] Preparando fotogramas y secuencias con FFmpeg…", file=sys.stderr)
        try:
            visual = inspect_media(media, stage, destination, metadata)
            if metadata["has_audio"]:
                try:
                    transcription = transcribe_media(media, args.model, args.language)
                    transcription = {**transcription, "status": "completed" if transcription["text"].strip() else "no_speech"}
                except ToolError as error:
                    if error.code != "no_audio":
                        raise
                    transcription = empty_transcription(args, metadata, "no_audio")
            else:
                transcription = empty_transcription(args, metadata, "no_audio")
            result = {
                "schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
                "source": source, "transcription": transcription, "visual": visual,
                "output_dir": str(destination),
            }
            serialized = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
            (stage / "inspection.json").write_text(serialized, encoding="utf-8")
            publish_inspection(stage, destination)
            return serialized
        except OSError as error:
            raise ToolError("output_unwritable", "No se pudo guardar el material de inspección.") from error


def empty_transcription(args, metadata, status):
    return {"engine": "openai-whisper", "model": args.model, "language": args.language,
            "duration_seconds": metadata["duration_seconds"], "status": status, "text": "", "segments": []}


def main(argv=None):
    try:
        args = parser().parse_args(argv)
        # Library progress must never corrupt the JSON consumed by an agent.
        with contextlib.redirect_stdout(sys.stderr):
            serialized = run(args)
        sys.stdout.write(serialized)
        return 0
    except ToolError as error:
        print(json.dumps({"error": {"code": error.code, "message": str(error)}}, ensure_ascii=False), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(json.dumps({"error": {"code": "interrupted", "message": "Operación cancelada."}}), file=sys.stderr)
        return 130
    except BrokenPipeError:
        return 141


if __name__ == "__main__":
    raise SystemExit(main())

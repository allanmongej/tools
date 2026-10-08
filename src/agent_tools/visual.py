"""Prepare bounded visual samples and motion evidence using FFmpeg only."""

import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .errors import ToolError


def ffmpeg_executable():
    installed = shutil.which("ffmpeg")
    if installed:
        return installed
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError) as error:
        raise ToolError("missing_dependency", "Instala las dependencias del proyecto con pip install -e .") from error


def ffmpeg_run(arguments, *, loglevel="error", check=True):
    try:
        result = subprocess.run(
            [ffmpeg_executable(), "-nostdin", "-hide_banner", "-loglevel", loglevel, "-n", *arguments],
            capture_output=True, timeout=300, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ToolError("video_processing_failed", "No se pudo completar el procesamiento de video con FFmpeg.") from error
    if check and result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()[-500:]
        raise ToolError("video_processing_failed", f"FFmpeg no pudo procesar el video: {detail}")
    return result


def video_metadata(path):
    probe = ffmpeg_run(["-i", str(path), "-map", "0:v:0", "-frames:v", "1", "-an", "-f", "null", "-"], loglevel="info", check=False)
    log = probe.stderr.decode("utf-8", errors="replace")
    video_line = next((line for line in log.splitlines() if "Stream #" in line and "Video:" in line), "")
    if not video_line:
        if "Audio:" in log:
            raise ToolError("no_video", "inspect necesita un video. Para audio utiliza transcribe.")
        raise ToolError("invalid_media", "No se pudo leer el archivo como video.")
    if probe.returncode:
        raise ToolError("invalid_media", "No se pudo decodificar el video.")
    duration = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", log)
    size = re.search(r",\s*(\d+)x(\d+)\b", video_line)
    rate = re.search(r"(\d+(?:\.\d+)?) fps", video_line)
    if not duration or not size:
        raise ToolError("invalid_media", "El video necesita dimensiones y una duración finita para inspeccionarlo.")
    seconds = int(duration[1]) * 3600 + int(duration[2]) * 60 + float(duration[3])
    if seconds <= 0:
        raise ToolError("invalid_media", "El video no tiene una duración utilizable.")
    return {
        "duration_seconds": round(seconds, 3),
        "width": int(size[1]), "height": int(size[2]),
        "fps": float(rate[1]) if rate else None,
        "has_audio": any("Stream #" in line and "Audio:" in line for line in log.splitlines()),
    }


def spaced(values, limit):
    """Keep coverage across the whole timeline when the sample budget is exceeded."""
    if len(values) <= limit:
        return values
    return [values[round(index * (len(values) - 1) / (limit - 1))] for index in range(limit)]


def extract_frame(media, time, destination, width=480):
    ffmpeg_run(["-ss", f"{time:.6f}", "-i", str(media), "-map", "0:v:0", "-frames:v", "1",
                "-vf", f"scale='min({width},iw)':-2", "-q:v", "3", str(destination)])
    if not destination.is_file():
        raise ToolError("video_processing_failed", f"No se pudo obtener el fotograma de {time:.3f} segundos.")


def sheet(pattern, destination, count, columns, width):
    rows = math.ceil(count / columns)
    ffmpeg_run(["-framerate", "1", "-i", str(pattern), "-frames:v", "1",
                "-vf", f"scale='min({width},iw)':-2,tile={columns}x{rows}:padding=8:margin=8:color=white",
                "-q:v", "3", str(destination)])


def inspect_media(media, stage, destination, metadata):
    """All final paths refer to the requested directory, not temporary downloads."""
    duration = metadata["duration_seconds"]
    scan = ffmpeg_run(["-i", str(media), "-map", "0:v:0", "-an", "-vf",
                       "scale='min(320,iw)':-2,select='gt(scene,0.3)',showinfo", "-f", "null", "-"], loglevel="info")
    candidates = sorted(set(round(float(time), 3) for time in re.findall(
        r"\bn:\s*\d+.*?pts_time:\s*([\d.]+)", scan.stderr.decode("utf-8", errors="replace")
    ) if 0 < float(time) < duration))
    # At most 48 overview frames, including the hook and both sides of sampled cuts.
    last = max(0, duration - max(0.1, 1 / (metadata["fps"] or 10)))
    interval = max(3.0, duration / 36)
    times = {0.0, last, min(1.0, last), min(2.0, last)}
    times.update(index * interval for index in range(1, math.ceil(duration / interval)) if index * interval <= last)
    sampled_cuts = spaced(candidates, 11)
    times.update(max(0, min(last, cut + offset)) for cut in sampled_cuts for offset in (-0.1, 0.1))
    times = spaced(sorted(set(round(time, 3) for time in times)), 48)
    frames = []
    for index, time in enumerate(times):
        name = f"frame-{index:03d}.jpg"
        extract_frame(media, time, stage / name)
        frames.append({"time": time, "path": str(destination / name)})
    sheet(stage / "frame-%03d.jpg", stage / "contact-sheet.jpg", len(frames), 4, 240)

    # Four-second excerpts plus four ordered frames expose motion and transitions.
    latest_start = max(0, duration - 4.0)
    starts = {0.0, latest_start}
    starts.update(max(0, min(latest_start, time - 1)) for time in sampled_cuts)
    starts.update(min(latest_start, duration * part / 4) for part in (1, 2, 3))
    starts = spaced(sorted(set(round(start, 3) for start in starts)), 12)
    sequences = []
    with tempfile.TemporaryDirectory(prefix="sequence-frames-") as temporary:
        scratch = Path(temporary)
        for index, start in enumerate(starts):
            end = min(duration, start + 4.0)
            clip = f"sequence-{index:02d}.mp4"
            strip = f"sequence-{index:02d}.jpg"
            ffmpeg_run(["-ss", f"{start:.6f}", "-i", str(media), "-t", f"{end - start:.6f}",
                        "-map", "0:v:0", "-map", "0:a:0?", "-vf", "scale='min(480,iw)':-2",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "25", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-movflags", "+faststart", str(stage / clip)])
            frame_end = min(last, max(start, end - 0.1))
            frame_times = [round(start + step * (frame_end - start) / 3, 3) for step in range(4)]
            for step, time in enumerate(frame_times):
                extract_frame(media, time, scratch / f"{index:02d}-{step:02d}.jpg", width=240)
            sheet(scratch / f"{index:02d}-%02d.jpg", stage / strip, 4, 4, 240)
            sequences.append({"start": start, "end": round(end, 3), "frame_times": frame_times,
                              "clip_path": str(destination / clip), "strip_path": str(destination / strip)})

    video_name = "source" + (media.suffix.lower() or ".video")
    shutil.copyfile(media, stage / video_name)
    return {
        **metadata, "video_path": str(destination / video_name),
        "scene_detection": {"engine": "ffmpeg", "threshold": 0.3, "candidate_cuts_only": True},
        "scene_candidates": candidates, "frames": frames,
        "contact_sheet": str(destination / "contact-sheet.jpg"), "contact_sheet_columns": 4,
        "sequences": sequences,
        "sampling": {"max_overview_frames": 48, "max_sequences": 12,
                     "sequence_seconds": 4, "full_video_retained": True},
    }

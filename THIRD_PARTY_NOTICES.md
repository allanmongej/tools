# Third-party software

The MIT license in this repository covers the original tools source code and
documentation. Dependencies and model weights retain their own licenses.
Dependencies are installed separately with pip; their code, binaries and model
weights are not included in this repository.

| Component | Direct dependency version | Upstream license |
| --- | --- | --- |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | 2026.8.19 | [Unlicense](https://github.com/yt-dlp/yt-dlp/blob/master/LICENSE) for the Python source/package used here. Other upstream release artifacts may include third-party components under additional licenses. |
| [OpenAI Whisper](https://github.com/openai/whisper) | 20250625 | [MIT](https://github.com/openai/whisper/blob/main/LICENSE). Whisper code and released model weights are covered by upstream's license. |
| [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) | 0.6.0 | [BSD-2-Clause](https://github.com/imageio/imageio-ffmpeg/blob/main/LICENSE) for the Python wrapper. |

FFmpeg is executed as a separate process. The binary supplied by the installed
imageio-ffmpeg wheel on the tested macOS arm64 system reports GPL version 2 or later.
Other builds may have different LGPL/GPL terms depending on their configuration;
see [FFmpeg's license information](https://ffmpeg.org/legal.html). The wrapper's
BSD license does not replace the binary's license. This repository does not
redistribute an FFmpeg binary or a prebuilt application containing dependencies.

Transitive dependencies keep their upstream licenses as well. A future release
that bundles dependencies or binaries must include their applicable notices and
meet their distribution requirements. Downloaded videos and their transcripts
are not relicensed by this project's MIT license.

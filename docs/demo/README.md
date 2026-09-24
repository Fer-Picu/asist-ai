# A real transcription run with synthetic input

This sample uses **synthetic English speech** generated locally with FFmpeg's Flite filter (`slt` voice). It is not Fernando's voice and does not demonstrate microphone capture or desktop interaction.

[Listen to / download the WAV](sample.wav) · [Input text](input.txt) · [Machine-readable result](result.json)

## Input

> Good software connects the pieces. This local voice tool records audio, removes silence, and turns speech into text. The result is ready to copy into a note.

## Observed output — September 24, 2026

> Good software connects the pieces, this local voice tool or records audio, removes silence and turns speech into text. The result is ready to copy into a note.

The extra word **“or”** and punctuation differences are retained exactly as observed. This output is not a corrected transcript.

| Measurement | This run |
| --- | --- |
| Input format | 16 kHz, mono, 16-bit PCM WAV |
| Original duration | 11.79 seconds |
| After WebRTC VAD | 10.22 seconds |
| Transcription wall time | 18.37 seconds |
| Model | `ggml-tiny.bin`, English, 4 threads |
| Platform | Linux x86_64 |

Timing covers the transcriber call, including the temporary WAV and model invocation, but excludes VAD. This is one local run under existing machine load, not a benchmark, latency guarantee or real-time claim.

## Reproduce

Install the project and whisper.cpp as described in the [README](../../README.md), then run from the repository root:

```bash
uv run python scripts/demo.py --model ~/.config/asit-ia/models/ggml-tiny.bin
```

The included WAV is sufficient; FFmpeg is only needed if you want to regenerate it. To regenerate with an FFmpeg build that includes Flite, write to a new file:

```bash
ffmpeg -f lavfi -i 'flite=textfile=docs/demo/input.txt:voice=slt' \
  -af 'adelay=1000,apad=pad_dur=1' -ar 16000 -ac 1 -c:a pcm_s16le \
  regenerated.wav
uv run python scripts/demo.py --audio regenerated.wav \
  --model ~/.config/asit-ia/models/ggml-tiny.bin
```

The text was written for this demonstration. Speech synthesis is provided by [Flite](http://www.festvox.org/flite/), through [FFmpeg](https://ffmpeg.org/ffmpeg-filters.html#flite); no voice model or third-party executable is bundled here.

## What this establishes

- The actual VAD and transcription classes can process this fixture using a real local Whisper model.
- Silence trimming and transcription produce the durations and output recorded above.
- The example can run without microphone or clipboard access.

It does **not** validate shortcut handling, microphone hardware, real-speaker accuracy, noise robustness, clipboard delivery, concurrency or production readiness. A desktop recording with an explicitly supplied voice sample remains a follow-up.

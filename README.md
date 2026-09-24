# Asist AI

**Local voice-to-text for the Linux desktop.**

Press a shortcut to record, press it again to stop, then paste the transcription from your clipboard. Asist AI connects Linux audio tools, WebRTC voice activity detection and whisper.cpp in a Python application.

The project name is **Asist AI**. The Python package and command remain `asit-ia`.

[Recorded pipeline demo](docs/demo/README.md) · [Architecture and trade-offs](docs/architecture.md) · [Portfolio](https://fer-picu.github.io/)

## Why I built it

I wanted dictation to fit into my Linux workflow: capture a thought, turn it into text locally, and use it in the application I already have open. The engineering work is connecting existing tools into a usable workflow and handling their process lifecycle and failure modes. I did not train Whisper or build its inference engine.

## How it works

```text
Desktop shortcut / CLI
  -> arecord or parecord: 16 kHz, mono, 16-bit PCM
  -> WebRTC VAD: retain speech-bearing segments
  -> whisper.cpp: transcribe with a local model
  -> Linux clipboard: text ready for manual paste
  -> best-effort desktop notification
```

Inference runs locally after the model and dependencies have been downloaded. This is a desktop tool, not a hosted AI service.

## Quick start

Requires Linux, Python 3.11+, [uv](https://docs.astral.sh/uv/getting-started/installation/), and a desktop clipboard backend.

On Ubuntu / Kubuntu, install the audio and clipboard tools:

```bash
sudo apt install alsa-utils pulseaudio-utils wl-clipboard libnotify-bin
```

Install [whisper.cpp](https://github.com/ggml-org/whisper.cpp#quick-start) following its build instructions and make `whisper-cli` available on `PATH`. The OpenAI Python `whisper` command is not a compatible substitute for `whisper-cli`.

```bash
git clone https://github.com/Fer-Picu/asist-ai.git
cd asist-ai
uv sync --locked --python 3.11
uv run asit-ia --download-model tiny
```

The first download needs internet access. Configuration is stored at `~/.config/asit-ia/config.yaml`. For English dictation, change the existing `model.language` value to `en`; preserve the other settings. The default language is Spanish (`es`), and the legacy `auto` value also selects Spanish.

```bash
uv run asit-ia --duration 5
```

Speak during those five seconds. Wait for transcription, then paste manually into a note. This command opens the microphone and replaces the clipboard contents when transcription succeeds.

For desktop use:

```bash
uv tool install .
```

Configure a desktop shortcut to run `~/.local/bin/asit-ia`. The first invocation starts recording; the next sends a stop signal. Choose a shortcut that does not conflict with your desktop settings. The primary workflow targets KDE / Wayland; other desktop combinations need validation.

## Reproducible demo without a microphone

```bash
uv run python scripts/demo.py --model ~/.config/asit-ia/models/ggml-tiny.bin
```

The included sample is explicitly **synthetic English speech**, generated from the original text in `docs/demo/input.txt`. The script runs the real VAD and transcription code and prints the observed transcript and timing. It does not touch the microphone, clipboard, desktop shortcuts or your configuration.

See the [demo record](docs/demo/README.md) for the input, output and scope. One synthetic sample is not an accuracy benchmark or proof that every desktop integration works.

## Validation

```bash
uv sync --locked --python 3.11
uv run pytest -q
uv build
```

The tests cover configuration, audio contracts, VAD, subprocess behavior, clipboard selection, notifications, recording duration and temporary-file isolation. External audio, clipboard and transcription calls are simulated in unit tests; the separate demo exercises real whisper.cpp inference.

## Data handling and current limits

- Recording is explicit; the app does not start an always-listening service. Do not configure it as an autostart service unless that is the behavior you want.
- The push-to-talk workflow retains diagnostic WAV files under `/tmp/asit-ia-recordings`. Files older than 24 hours are removed on a subsequent recording, on a best-effort basis. This is **not** a guarantee of deletion after exactly 24 hours. Avoid sensitive dictation on shared systems.
- Transcripts are logged and may remain in terminal or user-journal logs. Clipboard managers may also retain text in history.
- Temporary transcription files use a private, per-instance directory and are cleaned up after processing. An abrupt process termination can leave temporary data behind.
- Recording accumulates in memory. Use short recordings; this is not a streaming transcription system.
- Push-to-talk inference has a 120-second timeout. A timeout or empty result produces no clipboard update. Error exit codes and cancellation during inference still need improvement.
- Clipboard detection chooses the first installed backend (`qdbus6`, `wl-copy`, `xclip`, `xsel`). It does not retry another backend if the selected one fails.
- The PID-file toggle is a single-user prototype, not hardened for concurrent invocations. Legacy X11 injection code is retained, but the CLI uses clipboard output and does not type into the focused window.

## Attribution and reuse

The application integrates [whisper.cpp](https://github.com/ggml-org/whisper.cpp), [Whisper](https://github.com/openai/whisper), [py-webrtcvad](https://github.com/wiseman/py-webrtcvad), PyYAML and Linux desktop tools. These retain their own licenses. Model weights and third-party binaries are not included.

This repository is published for portfolio review. No open-source license has been granted for the application code yet.

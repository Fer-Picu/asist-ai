# Architecture and engineering decisions

Asist AI is a Python integration layer around local audio, inference and desktop tools. Its primary public workflow is push-to-talk dictation with clipboard output.

| Component | Responsibility | Contract |
| --- | --- | --- |
| CLI | Parse configuration and toggle recording | An explicit invocation starts or stops the recorder |
| Capture | Manage `arecord` / `parecord` subprocesses | 16 kHz mono signed 16-bit PCM |
| VAD | Select speech-bearing frames | WebRTC VAD; original audio retained if no speech is detected |
| Transcription | Call `whisper-cli` and collect text | Local model, validated WAV, bounded inference in push-to-talk |
| Clipboard | Send text to an installed desktop backend | Clipboard contents; manual paste by the user |
| Notification | Signal completion without breaking transcription | Best-effort desktop message and sound |

## Why a subprocess boundary?

whisper.cpp owns inference. Python owns the workflow: arguments, formats, start/stop behavior, output handling and error reporting. This avoids pretending the application implements speech recognition itself, but makes external binary installation and process cancellation part of the integration contract.

## Why clipboard output?

Clipboard output fits the normal paste workflow and avoids relying on simulated typing into arbitrary applications. Desktop dependencies still matter: the first installed backend is selected, and a installed-but-unusable backend does not trigger fallback. KDE Klipper can keep a history of clipboard contents.

## Why retain a VAD fallback?

VAD can misclassify speech. If it returns no speech-bearing segment, the tool transcribes the original recording. This favors retaining the user's input over dropping it silently, but silence-only input can still produce unwanted model output.

## Changes in this public snapshot

- The advertised `--duration` option now stops push-to-talk recording and rejects non-positive or non-finite values.
- Push-to-talk passes a 120-second timeout to the existing transcription process wrapper.
- Each transcriber gets its own private temporary directory; cleaning up one instance no longer removes another instance's temporary files.
- The README describes clipboard output, diagnostic recordings, logs and remaining limits explicitly.
- The demo exercises the real VAD/transcriber boundary using a synthetic fixture, without recording audio or accessing the desktop clipboard.

This is a curated snapshot of the original personal project. Private development notes, local configuration, model files and historical recordings are not part of the export.

## Boundaries of the evidence

Unit tests isolate hardware, clipboard and inference using test doubles. The recorded demo separately validates a real model invocation from a WAV file. Neither proves microphone capture, desktop shortcut behavior or recognition accuracy across speakers and noisy rooms. A real desktop demonstration is a separate follow-up.

The application remains a single-user prototype. Concurrent starts, PID-file ownership, memory limits for long recordings, diagnostic audio permissions, cancellation during inference and consistent error exit codes are areas for further work.

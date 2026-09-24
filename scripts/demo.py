"""Transcribe a supplied WAV through the real VAD and whisper.cpp pipeline.

No microphone, clipboard, desktop notifications or user configuration are used.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import platform
import time
import wave
from pathlib import Path

from asit_ia.audio.vad import trim_silence
from asit_ia.transcription.whisper import WhisperTranscriber


async def run(args: argparse.Namespace) -> dict:
    with wave.open(str(args.audio), "rb") as audio:
        if (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) != (16000, 1, 2):
            raise ValueError("Input must be 16 kHz, mono, 16-bit PCM WAV")
        pcm = audio.readframes(audio.getnframes())
    trimmed = trim_silence(pcm)
    transcriber = WhisperTranscriber(args.model, threads=4, language="en", timeout=120)
    started = time.perf_counter()
    try:
        transcript = await transcriber.transcribe_pcm(trimmed)
    finally:
        transcriber.cleanup_temp()
    if not transcript:
        raise RuntimeError("Transcription returned no text; check whisper-cli and the model")
    return {
        "input": args.audio.name,
        "input_sha256": hashlib.sha256(args.audio.read_bytes()).hexdigest(),
        "model": args.model.name,
        "language": "en",
        "threads": 4,
        "platform": f"{platform.system()} {platform.machine()}",
        "input_seconds": round(len(pcm) / 32000, 2),
        "trimmed_seconds": round(len(trimmed) / 32000, 2),
        "transcription_seconds": round(time.perf_counter() - started, 2),
        "transcript": transcript,
        "scope": "File -> real WebRTC VAD -> real whisper.cpp. Microphone, clipboard and desktop shortcut are not exercised.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--audio", type=Path, default=Path("docs/demo/sample.wav"))
    arguments = parser.parse_args()
    print(json.dumps(asyncio.run(run(arguments)), indent=2))

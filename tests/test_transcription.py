from __future__ import annotations

import asyncio
import wave
from pathlib import Path

import pytest

from asit_ia.transcription.whisper import ModelNotFoundError, WhisperTranscriber, _clean_output


def write_wav(path: Path, *, sample_rate: int, channels: int, sample_width: int = 2) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(sample_width)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\0" * sample_width * channels * 10)


def test_missing_model_raises_exit_code_two_error(tmp_path: Path) -> None:
    transcriber = WhisperTranscriber(tmp_path / "missing.bin")

    with pytest.raises(ModelNotFoundError, match="Whisper model not found"):
        transcriber.ensure_model()


def test_invalid_wav_is_rejected_without_launching_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = tmp_path / "ggml-tiny.bin"
    model.write_bytes(b"model")
    invalid_wav = tmp_path / "invalid.wav"
    write_wav(invalid_wav, sample_rate=48000, channels=2)
    transcriber = WhisperTranscriber(model)

    async def fail_if_called(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("subprocess should not be launched for invalid WAV")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fail_if_called)

    assert asyncio.run(transcriber.transcribe_wav(invalid_wav)) == ""


def test_clean_output_strips_whisper_timestamps() -> None:
    assert _clean_output("[00:00:00.000 --> 00:00:01.000] hola\n mundo\n") == "hola mundo"


def test_timeout_kills_whisper_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    model = tmp_path / "ggml-tiny.bin"
    model.write_bytes(b"model")
    wav_path = tmp_path / "valid.wav"
    write_wav(wav_path, sample_rate=16000, channels=1)
    transcriber = WhisperTranscriber(model, timeout=0.01)

    class HungProcess:
        returncode = None
        stdout = None
        stderr = None

        def __init__(self) -> None:
            self.terminated = False
            self.killed = False

        async def communicate(self) -> tuple[bytes, bytes]:
            await asyncio.sleep(1)
            return b"", b""

        def terminate(self) -> None:
            self.terminated = True

        def kill(self) -> None:
            self.killed = True

        async def wait(self) -> int:
            await asyncio.sleep(1)
            return 0

    process = HungProcess()

    async def fake_subprocess(*_args: object, **_kwargs: object) -> HungProcess:
        return process

    monkeypatch.setattr("shutil.which", lambda _name: "whisper-cli")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)

    assert asyncio.run(transcriber.transcribe_wav(wav_path)) == ""
    assert process.terminated is True


def test_auto_language_runs_whisper_in_spanish(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    model = tmp_path / "ggml-tiny.bin"
    model.write_bytes(b"model")
    wav_path = tmp_path / "valid.wav"
    write_wav(wav_path, sample_rate=16000, channels=1)
    transcriber = WhisperTranscriber(model, language="auto")
    captured_cmd: list[str] = []

    class Process:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"hola", b""

    async def fake_subprocess(*cmd: str, **_kwargs: object) -> Process:
        captured_cmd.extend(cmd)
        return Process()

    monkeypatch.setattr("shutil.which", lambda _name: "whisper-cli")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)

    assert asyncio.run(transcriber.transcribe_wav(wav_path)) == "hola"
    assert captured_cmd[captured_cmd.index("-l") + 1] == "es"

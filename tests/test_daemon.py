from __future__ import annotations

import asyncio
import os
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from asit_ia.audio.capture import CaptureError
from asit_ia.config import Config
from asit_ia.daemon import MainLoop, PushToTalkLoop, _cleanup_old_recordings


# ------------------------------------------------------------------
# Injector factory
# ------------------------------------------------------------------


def _minimal_config(mode: str) -> MagicMock:
    """Build a Config-like stub with just enough for __post_init__."""
    cfg = MagicMock(spec=Config)
    cfg.injection.mode = mode
    cfg.injection.display = ":0"
    cfg.injection.typing_speed_ms = 0
    cfg.audio.sample_rate = 16000
    cfg.audio.channels = 1
    cfg.audio.format = "S16_LE"
    cfg.audio.silence_timeout_ms = 500
    cfg.vad.frame_ms = 20
    cfg.vad.aggressiveness = 3
    cfg.vad.ring_buffer_seconds = 2.0
    cfg.model.path = "model.bin"
    cfg.model.threads = 4
    cfg.model.language = "auto"
    return cfg


@patch("asit_ia.daemon.ArecordCapture", MagicMock())
@patch("asit_ia.daemon.VadGate", MagicMock())
@patch("asit_ia.daemon.WhisperTranscriber", MagicMock())
def test_daemon_creates_clipboard_injector_in_clipboard_mode() -> None:
    cfg = _minimal_config("clipboard")
    with patch("asit_ia.injection.clipboard.shutil.which", return_value="/usr/bin/wl-copy"):
        loop = MainLoop(config=cfg)

    from asit_ia.injection.clipboard import ClipboardInjector

    assert isinstance(loop.injector, ClipboardInjector)


@patch("asit_ia.daemon.ArecordCapture", MagicMock())
@patch("asit_ia.daemon.VadGate", MagicMock())
@patch("asit_ia.daemon.WhisperTranscriber", MagicMock())
def test_daemon_creates_xtest_injector_in_injection_mode() -> None:
    cfg = _minimal_config("injection")
    loop = MainLoop(config=cfg)

    from asit_ia.injection.xtest import XtestInjector

    assert isinstance(loop.injector, XtestInjector)


# ------------------------------------------------------------------
# Startup checks
# ------------------------------------------------------------------


def test_startup_checks_skip_xtest_when_mode_clipboard() -> None:
    """_startup_checks should not raise even without DISPLAY when mode=clipboard."""
    loop = MainLoop.__new__(MainLoop)
    loop.config = _minimal_config("clipboard")

    class DummyTranscriber:
        def ensure_model(self) -> None:
            pass

    loop.transcriber = DummyTranscriber()

    class AlwaysTrueInjector:
        def detect_display(self) -> bool:
            return True

    loop.injector = AlwaysTrueInjector()

    # Should not raise
    loop._startup_checks()


def test_pipeline_treats_closed_arecord_as_critical_capture_error() -> None:
    loop = MainLoop.__new__(MainLoop)
    loop.shutdown = asyncio.Event()

    class FakeCapture:
        class Process:
            returncode = 1

        process = Process()

    class FakeVad:
        frame_bytes = 640

    loop.capture = FakeCapture()
    loop.vad = FakeVad()

    with pytest.raises(CaptureError, match="arecord exited with code 1"):
        asyncio.run(loop._pipeline())


def test_transcription_failure_is_non_fatal_and_injects_no_text() -> None:
    loop = MainLoop.__new__(MainLoop)

    class FailingTranscriber:
        async def transcribe_pcm(self, *_args: object, **_kwargs: object) -> str:
            raise RuntimeError("boom")

    class SpyInjector:
        sent: list[str] = []

        def send_text(self, text: str) -> None:
            self.sent.append(text)

    loop.config = type(
        "ConfigStub",
        (),
        {"audio": type("AudioStub", (), {"sample_rate": 16000, "channels": 1})()},
    )()
    loop.transcriber = FailingTranscriber()
    loop.injector = SpyInjector()

    asyncio.run(loop._process_segment(b"pcm"))

    assert loop.injector.sent == []


def test_process_segment_notifies_after_successful_injection() -> None:
    loop = MainLoop.__new__(MainLoop)

    class Transcriber:
        async def transcribe_pcm(self, *_args: object, **_kwargs: object) -> str:
            return "hola"

    class SpyInjector:
        sent: list[str] = []

        def send_text(self, text: str) -> None:
            self.sent.append(text)

    loop.config = type(
        "ConfigStub",
        (),
        {"audio": type("AudioStub", (), {"sample_rate": 16000, "channels": 1})()},
    )()
    loop.transcriber = Transcriber()
    loop.injector = SpyInjector()

    with patch("asit_ia.daemon.notify_ready") as mock_notify:
        asyncio.run(loop._process_segment(b"pcm"))

    assert loop.injector.sent == ["hola"]
    mock_notify.assert_called_once_with()


def test_push_to_talk_writes_recording_to_shared_tmp_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recordings_dir = tmp_path / "recordings"
    monkeypatch.setattr("asit_ia.daemon.RECORDINGS_DIR", recordings_dir)
    monkeypatch.setattr("asit_ia.daemon.time.strftime", lambda _fmt: "20260614-010203")

    loop = PushToTalkLoop.__new__(PushToTalkLoop)
    loop.config = _minimal_config("clipboard")

    wav_path = loop._write_wav(b"\x00\x00" * 160)

    assert wav_path.parent == recordings_dir
    assert wav_path.name.endswith(".wav")
    with wave.open(str(wav_path), "rb") as wf:
        assert wf.getframerate() == 16000
        assert wf.getnchannels() == 1
        assert wf.getnframes() == 160


def test_cleanup_old_recordings_removes_only_expired_wavs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recordings_dir = tmp_path / "recordings"
    recordings_dir.mkdir()
    old_wav = recordings_dir / "old.wav"
    fresh_wav = recordings_dir / "fresh.wav"
    old_txt = recordings_dir / "old.txt"
    old_wav.write_bytes(b"old")
    fresh_wav.write_bytes(b"fresh")
    old_txt.write_bytes(b"old text")

    now = 100_000.0
    os.utime(old_wav, (now - 90_000, now - 90_000))
    os.utime(fresh_wav, (now, now))
    os.utime(old_txt, (now - 90_000, now - 90_000))
    monkeypatch.setattr("asit_ia.daemon.RECORDINGS_DIR", recordings_dir)

    _cleanup_old_recordings(now=now)

    assert not old_wav.exists()
    assert fresh_wav.exists()
    assert old_txt.exists()

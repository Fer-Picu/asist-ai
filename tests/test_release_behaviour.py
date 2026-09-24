"""Regression checks for the public release, without audio or clipboard access."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from asit_ia.__main__ import build_parser, main
from asit_ia.config import Config
from asit_ia.daemon import PushToTalkLoop
from asit_ia.transcription.whisper import WhisperTranscriber


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf"])
def test_invalid_duration_is_rejected(value):
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--duration", value])


def test_cli_passes_duration_to_recording_loop():
    config = Config.defaults()
    with (
        patch("asit_ia.__main__._pid_alive", return_value=False),
        patch("asit_ia.__main__.detect_default_source", return_value=None),
        patch("asit_ia.__main__.load_config", return_value=config),
        patch("asit_ia.__main__.run_push_to_talk", new_callable=AsyncMock) as run,
    ):
        run.return_value = 0
        assert main(["--duration", "0.1"]) == 0
        run.assert_awaited_once_with(config, duration=0.1)


def test_recording_stops_after_duration_without_a_signal(tmp_path, monkeypatch):
    monkeypatch.setattr("asit_ia.daemon.PID_FILE", tmp_path / "pid")

    async def record_until_shutdown(self):
        await asyncio.wait_for(self.shutdown.wait(), timeout=1)

    with (
        patch("asit_ia.daemon.ClipboardInjector"),
        patch("asit_ia.daemon.WhisperTranscriber"),
        patch("asit_ia.daemon.ArecordCapture") as capture,
        patch.object(PushToTalkLoop, "_install_signal_handlers"),
        patch.object(PushToTalkLoop, "_record", record_until_shutdown),
        patch.object(PushToTalkLoop, "_finish", new_callable=AsyncMock),
    ):
        capture.return_value.start = AsyncMock()
        loop = PushToTalkLoop(Config.defaults(), duration=0.01)
        assert asyncio.run(loop.run()) == 0
        assert loop.shutdown.is_set()


def test_transcription_cleanup_does_not_remove_another_instances_files(tmp_path):
    first = WhisperTranscriber(tmp_path / "model.bin")
    second = WhisperTranscriber(tmp_path / "model.bin")
    try:
        recording = second.temp_dir / "segment.wav"
        recording.write_bytes(b"audio")
        first.cleanup_temp()
        assert recording.read_bytes() == b"audio"
        assert second.temp_dir.stat().st_mode & 0o777 == 0o700
    finally:
        first.cleanup_temp()
        second.cleanup_temp()

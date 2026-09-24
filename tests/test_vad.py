from __future__ import annotations

import pytest

from asit_ia.audio.vad import VadGate, VadState, trim_silence


class FakeVad:
    def __init__(self, decisions: list[bool]) -> None:
        self.decisions = decisions

    def is_speech(self, _frame: bytes, _sample_rate: int) -> bool:
        assert self.decisions, "test did not provide enough VAD decisions"
        return self.decisions.pop(0)


def frame(gate: VadGate, value: int = 0) -> bytes:
    return bytes([value]) * gate.frame_bytes


def test_vad_detects_speech_after_three_consecutive_speech_frames() -> None:
    gate = VadGate()
    gate.vad = FakeVad([False, True, True, True])  # type: ignore[assignment]

    assert gate.feed(frame(gate)) is VadState.SILENCE
    assert gate.feed(frame(gate)) is VadState.SILENCE
    assert gate.feed(frame(gate)) is VadState.SILENCE
    assert gate.feed(frame(gate)) is VadState.SPEECH
    assert gate.in_speech is True


def test_vad_flushes_after_configured_silence_hangover() -> None:
    gate = VadGate(silence_hangover_ms=40)
    gate.vad = FakeVad([True, True, True, False, False])  # type: ignore[assignment]

    assert gate.feed(frame(gate, 1)) is VadState.SILENCE
    assert gate.feed(frame(gate, 2)) is VadState.SILENCE
    assert gate.feed(frame(gate, 3)) is VadState.SPEECH
    assert gate.feed(frame(gate, 4)) is VadState.SPEECH
    assert gate.feed(frame(gate, 5)) is VadState.FLUSH

    flushed = gate.flush()
    assert len(flushed) == 5 * gate.frame_bytes
    assert gate.in_speech is False


def test_short_noise_spike_is_ignored() -> None:
    gate = VadGate()
    gate.vad = FakeVad([True, False, False])  # type: ignore[assignment]

    assert gate.feed(frame(gate)) is VadState.SILENCE
    assert gate.feed(frame(gate)) is VadState.SILENCE
    assert gate.feed(frame(gate)) is VadState.SILENCE
    assert gate.drain() == b""


def test_vad_rejects_wrong_frame_size() -> None:
    gate = VadGate()

    with pytest.raises(ValueError, match="expected 640 bytes"):
        gate.feed(b"too short")


def test_trim_silence_keeps_detected_speech_region(monkeypatch: pytest.MonkeyPatch) -> None:
    decisions = [False, False, True, True, True, False, False]

    class FakeWebRtcVad:
        def __init__(self, _aggressiveness: int) -> None:
            pass

        def is_speech(self, _frame: bytes, _sample_rate: int) -> bool:
            return decisions.pop(0)

    monkeypatch.setattr("asit_ia.audio.vad.webrtcvad.Vad", FakeWebRtcVad)
    gate = VadGate(ring_buffer_seconds=0.02)
    pcm = b"".join(bytes([idx]) * gate.frame_bytes for idx in range(7))

    trimmed = trim_silence(
        pcm,
        frame_ms=gate.frame_ms,
        silence_hangover_ms=40,
        ring_buffer_seconds=0.02,
    )

    assert len(trimmed) == 3 * gate.frame_bytes
    assert trimmed.startswith(bytes([4]) * gate.frame_bytes)


def test_trim_silence_falls_back_to_original_when_no_speech_detected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeWebRtcVad:
        def __init__(self, _aggressiveness: int) -> None:
            pass

        def is_speech(self, _frame: bytes, _sample_rate: int) -> bool:
            return False

    monkeypatch.setattr("asit_ia.audio.vad.webrtcvad.Vad", FakeWebRtcVad)
    gate = VadGate()
    pcm = b"\x00" * gate.frame_bytes * 3

    assert trim_silence(pcm, frame_ms=gate.frame_ms) == pcm

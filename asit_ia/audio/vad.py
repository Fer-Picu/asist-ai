from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto

import webrtcvad


class VadState(Enum):
    SILENCE = auto()
    SPEECH = auto()
    FLUSH = auto()


@dataclass(slots=True)
class VadGate:
    sample_rate: int = 16000
    frame_ms: int = 20
    aggressiveness: int = 3
    silence_hangover_ms: int = 500
    ring_buffer_seconds: float = 2.0
    onset_frames: int = 3
    vad: webrtcvad.Vad = field(init=False)
    ring: deque[bytes] = field(init=False)
    speech_frames: list[bytes] = field(default_factory=list, init=False)
    in_speech: bool = field(default=False, init=False)
    consecutive_speech: int = field(default=0, init=False)
    consecutive_silence: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.vad = webrtcvad.Vad(self.aggressiveness)
        max_frames = int(self.ring_buffer_seconds * 1000 / self.frame_ms)
        self.ring = deque(maxlen=max_frames)

    @property
    def frame_bytes(self) -> int:
        return int(self.sample_rate * self.frame_ms / 1000) * 2

    @property
    def silence_frames(self) -> int:
        return max(1, int(self.silence_hangover_ms / self.frame_ms))

    def feed(self, pcm_chunk: bytes) -> VadState:
        if len(pcm_chunk) != self.frame_bytes:
            raise ValueError(f"expected {self.frame_bytes} bytes per VAD frame, got {len(pcm_chunk)}")

        is_speech = self.vad.is_speech(pcm_chunk, self.sample_rate)
        self.ring.append(pcm_chunk)

        if not self.in_speech:
            self.consecutive_speech = self.consecutive_speech + 1 if is_speech else 0
            if self.consecutive_speech >= self.onset_frames:
                self.in_speech = True
                self.consecutive_silence = 0
                self.speech_frames = list(self.ring)
                return VadState.SPEECH
            return VadState.SILENCE

        self.speech_frames.append(pcm_chunk)
        if is_speech:
            self.consecutive_silence = 0
            return VadState.SPEECH

        self.consecutive_silence += 1
        if self.consecutive_silence >= self.silence_frames:
            return VadState.FLUSH
        return VadState.SPEECH

    def flush(self) -> bytes:
        data = b"".join(self.speech_frames)
        self.speech_frames.clear()
        self.in_speech = False
        self.consecutive_speech = 0
        self.consecutive_silence = 0
        self.ring.clear()
        return data

    def drain(self) -> bytes:
        if not self.speech_frames:
            return b""
        return self.flush()


def trim_silence(
    pcm_data: bytes,
    *,
    sample_rate: int = 16000,
    frame_ms: int = 20,
    aggressiveness: int = 3,
    silence_hangover_ms: int = 500,
    ring_buffer_seconds: float = 0.3,
) -> bytes:
    """Return speech-bearing PCM detected by WebRTC VAD.

    Falls back to the original PCM when no speech is detected, so a VAD false
    negative never discards the user's recording.
    """
    gate = VadGate(
        sample_rate=sample_rate,
        frame_ms=frame_ms,
        aggressiveness=aggressiveness,
        silence_hangover_ms=silence_hangover_ms,
        ring_buffer_seconds=ring_buffer_seconds,
    )
    frame_bytes = gate.frame_bytes
    if len(pcm_data) < frame_bytes:
        return pcm_data

    speech_segments: list[bytes] = []
    usable_bytes = len(pcm_data) - (len(pcm_data) % frame_bytes)
    for offset in range(0, usable_bytes, frame_bytes):
        frame = pcm_data[offset : offset + frame_bytes]
        state = gate.feed(frame)
        if state is VadState.FLUSH:
            speech_segments.append(gate.flush())

    drained = gate.drain()
    if drained:
        speech_segments.append(drained)

    trimmed = b"".join(speech_segments)
    return trimmed or pcm_data

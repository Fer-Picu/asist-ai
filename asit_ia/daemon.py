from __future__ import annotations

import asyncio
import logging
import signal
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from asit_ia.audio.capture import ArecordCapture, CaptureError
from asit_ia.audio.vad import trim_silence
from asit_ia.config import Config
from asit_ia.injection.abc import Injector
from asit_ia.injection.clipboard import ClipboardError, ClipboardInjector
from asit_ia.notification import notify_failed, notify_ready
from asit_ia.transcription.whisper import ModelNotFoundError, WhisperTranscriber

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)

PID_FILE = Path("/tmp/asit-ia.pid")
RECORDINGS_DIR = Path("/tmp/asit-ia-recordings")
RECORDING_RETENTION_SECONDS = 24 * 60 * 60


# ── push-to-talk loop ──────────────────────────────────────────────

@dataclass(slots=True)
class PushToTalkLoop:
    """Record continuously until SIGTERM, then transcribe everything at once."""

    config: Config
    duration: float | None = None
    exit_code: int = 0
    shutdown: asyncio.Event = field(init=False)
    force_shutdown: bool = field(init=False, default=False)
    capture: ArecordCapture = field(init=False)
    transcriber: WhisperTranscriber = field(init=False)
    injector: Injector = field(init=False)
    _pcm_chunks: list[bytes] = field(init=False, default_factory=list)

    def __post_init__(self) -> None:
        self.shutdown = asyncio.Event()
        self.capture = ArecordCapture(
            sample_rate=self.config.audio.sample_rate,
            channels=self.config.audio.channels,
            audio_format=self.config.audio.format,
        )
        self.transcriber = WhisperTranscriber(
            model_path=self.config.model.path,
            threads=self.config.model.threads,
            language=self.config.model.language,
            timeout=120,
        )
        self.injector = ClipboardInjector()

    async def run(self) -> int:
        loop = asyncio.get_running_loop()
        self._install_signal_handlers(loop)
        stop_timer = None
        try:
            self.transcriber.ensure_model()
            PID_FILE.write_text(str(self._pid()))
            await self.capture.start(self.config.audio.device)
            if self.duration is not None:
                stop_timer = loop.call_later(self.duration, self.shutdown.set)
            log.info(
                "🎙️  Recording — press shortcut again to stop  (pid %d)",
                self._pid(),
            )
            await self._record()
        except ModelNotFoundError as exc:
            log.error("%s", exc)
            self.exit_code = 2
        except CaptureError as exc:
            log.error("audio capture failed: %s", exc)
            self.exit_code = 1
        except ClipboardError as exc:
            log.error("%s", exc)
            self.exit_code = 3
        finally:
            if stop_timer is not None:
                stop_timer.cancel()
            await self._finish()
        return self.exit_code

    async def _record(self) -> None:
        read_size = 4096
        while not self.shutdown.is_set():
            if self.capture.process and self.capture.process.returncode is not None:
                raise CaptureError(
                    f"recorder exited with code {self.capture.process.returncode}"
                )
            try:
                chunk = await asyncio.wait_for(
                    self.capture.read(read_size), timeout=1.0
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.IncompleteReadError as exc:
                raise CaptureError("recorder pipe closed") from exc
            self._pcm_chunks.append(chunk)

    async def _finish(self) -> None:
        await self.capture.stop(kill=self.force_shutdown)
        PID_FILE.unlink(missing_ok=True)
        pcm_data = b"".join(self._pcm_chunks)
        self._pcm_chunks.clear()

        if self.force_shutdown:
            log.warning("Forced shutdown — discarding audio")
            self.transcriber.cleanup_temp()
            return
        if not pcm_data:
            log.warning("No audio recorded")
            self.transcriber.cleanup_temp()
            return

        original_audio_seconds = len(pcm_data) / (self.config.audio.sample_rate * 2)
        trimmed_pcm = trim_silence(
            pcm_data,
            sample_rate=self.config.audio.sample_rate,
            frame_ms=self.config.vad.frame_ms,
            aggressiveness=self.config.vad.aggressiveness,
            silence_hangover_ms=self.config.audio.silence_timeout_ms,
        )
        audio_seconds = len(trimmed_pcm) / (self.config.audio.sample_rate * 2)
        if len(trimmed_pcm) != len(pcm_data):
            log.info(
                "✂️  VAD trimmed audio %.1fs → %.1fs",
                original_audio_seconds,
                audio_seconds,
            )
        wav_path = self._write_wav(trimmed_pcm)
        wav_size_kib = wav_path.stat().st_size / 1024
        log.info("🔇 Recording stopped — transcribing %.1fs of audio...", audio_seconds)
        t0 = time.monotonic()
        try:
            text = await self.transcriber.transcribe_wav(wav_path)
        except Exception:
            text = ""
        t1 = time.monotonic()

        if text:
            log.info("📋 %s", text)
            try:
                self.injector.send_text(text)
            except ClipboardError:
                raise
            t2 = time.monotonic()
            timing = (
                f"Lista · transcribir {t1 - t0:.1f}s · "
                f"clipboard {t2 - t1:.1f}s · total {t2 - t0:.1f}s · "
                f"audio {original_audio_seconds:.1f}s→{audio_seconds:.1f}s · "
                f"wav {wav_size_kib:.0f} KiB"
            )
            log.info("⏱️ %s", timing)
            notify_ready()
        else:
            log.warning(
                "Transcription produced no text · audio %.1fs→%.1fs · wav %.0f KiB",
                original_audio_seconds,
                audio_seconds,
                wav_size_kib,
            )
            notify_failed()
        self.transcriber.cleanup_temp()

    def _write_wav(self, pcm_data: bytes) -> Path:
        _cleanup_old_recordings()
        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        wav_path = RECORDINGS_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-{self._pid()}.wav"
        with wave.open(str(wav_path), "wb") as wf:
            wf.setnchannels(self.config.audio.channels)
            wf.setsampwidth(2)
            wf.setframerate(self.config.audio.sample_rate)
            wf.writeframes(pcm_data)
        return wav_path

    def _install_signal_handlers(self, loop: asyncio.AbstractEventLoop) -> None:
        def handler() -> None:
            if self.shutdown.is_set():
                self.force_shutdown = True
            self.shutdown.set()

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, handler)
            except NotImplementedError:
                signal.signal(sig, lambda *_: handler())

    @staticmethod
    def _pid() -> int:
        return __import__("os").getpid()


async def run_push_to_talk(config: Config, duration: float | None = None) -> int:
    return await PushToTalkLoop(config, duration=duration).run()


def _cleanup_old_recordings(now: float | None = None) -> None:
    """Best-effort retention cleanup for diagnostic WAV recordings."""
    if not RECORDINGS_DIR.exists():
        return

    cutoff = (time.time() if now is None else now) - RECORDING_RETENTION_SECONDS
    for path in RECORDINGS_DIR.glob("*.wav"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError as exc:
            log.debug("recording cleanup skipped %s: %s", path, exc)


# ── legacy continuous-VAD loop (kept for backward compat / injection mode) ───

from asit_ia.audio.vad import VadGate, VadState  # noqa: E402
from asit_ia.injection.xtest import XTestError  # noqa: E402


@dataclass(slots=True)
class MainLoop:
    config: Config
    duration: float | None = None
    exit_code: int = 0
    shutdown: asyncio.Event = field(init=False)
    force_shutdown: bool = field(init=False, default=False)
    capture: ArecordCapture = field(init=False)
    vad: VadGate = field(init=False)
    transcriber: WhisperTranscriber = field(init=False)
    injector: Injector = field(init=False)
    _speech_started: bool = field(init=False, default=False)
    _tasks: set[asyncio.Task] = field(init=False, default_factory=set)

    def __post_init__(self) -> None:
        self.shutdown = asyncio.Event()
        self.force_shutdown = False
        self.capture = ArecordCapture(
            sample_rate=self.config.audio.sample_rate,
            channels=self.config.audio.channels,
            audio_format=self.config.audio.format,
        )
        self.vad = VadGate(
            sample_rate=self.config.audio.sample_rate,
            frame_ms=self.config.vad.frame_ms,
            aggressiveness=self.config.vad.aggressiveness,
            silence_hangover_ms=self.config.audio.silence_timeout_ms,
            ring_buffer_seconds=self.config.vad.ring_buffer_seconds,
        )
        self.transcriber = WhisperTranscriber(
            model_path=self.config.model.path,
            threads=self.config.model.threads,
            language=self.config.model.language,
        )
        if self.config.injection.mode == "injection":
            from asit_ia.injection.xtest import XtestInjector  # noqa: PLC0415

            self.injector = XtestInjector(
                display=self.config.injection.display,
                typing_speed_ms=self.config.injection.typing_speed_ms,
            )
        else:
            self.injector = ClipboardInjector()

    async def run(self) -> int:
        loop = asyncio.get_running_loop()
        self._install_signal_handlers(loop)
        if self.duration:
            loop.call_later(self.duration, self.shutdown.set)
            log.info("Recording for %.0f seconds (--duration)", self.duration)
        try:
            self._startup_checks()
            await self.capture.start(self.config.audio.device)
            await self._pipeline()
        except ModelNotFoundError as exc:
            log.error("%s", exc)
            self.exit_code = 2
        except (ClipboardError, XTestError) as exc:
            log.error("%s", exc)
            self.exit_code = 3
        except CaptureError as exc:
            log.error("audio capture failed: %s", exc)
            self.exit_code = 1
        finally:
            await self._cleanup()
        return self.exit_code

    def _startup_checks(self) -> None:
        self.transcriber.ensure_model()
        if self.config.injection.mode == "injection" and not self.injector.detect_display():
            raise XTestError("XTEST requires XWayland. DISPLAY=:0 not available.")

    async def _pipeline(self) -> None:
        frame_bytes = self.vad.frame_bytes
        while not self.shutdown.is_set():
            if self.capture.process and self.capture.process.returncode is not None:
                raise CaptureError(f"arecord exited with code {self.capture.process.returncode}")
            try:
                frame = await asyncio.wait_for(self.capture.read(frame_bytes), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.IncompleteReadError as exc:
                raise CaptureError("arecord pipe closed") from exc
            state = self.vad.feed(frame)
            if state is VadState.SPEECH:
                if not self._speech_started:
                    self._speech_started = True
                    log.info("🎤 Voice detected — recording")
            elif state is VadState.FLUSH:
                self._speech_started = False
                log.info("🔇 Silence — transcribing...")
                await self._process_segment(self.vad.flush())

    async def _process_segment(self, pcm_data: bytes) -> None:
        if not pcm_data:
            return
        audio_seconds = len(pcm_data) / (self.config.audio.sample_rate * 2)
        pcm_size_kib = len(pcm_data) / 1024
        t0 = time.monotonic()
        try:
            text = await self.transcriber.transcribe_pcm(
                pcm_data,
                sample_rate=self.config.audio.sample_rate,
                channels=self.config.audio.channels,
            )
        except ModelNotFoundError:
            raise
        except Exception as exc:
            log.exception("transcription failed for segment: %s", exc)
            return
        t1 = time.monotonic()
        if not text:
            log.warning(
                "Transcription produced no text · audio %.1fs · pcm %.0f KiB",
                audio_seconds,
                pcm_size_kib,
            )
            notify_failed()
            return
        log.info("📋 %s", text)
        try:
            self.injector.send_text(text)
        except (ClipboardError, XTestError):
            raise
        except Exception as exc:
            log.exception("text injection failed: %s", exc)
            raise XTestError(str(exc)) from exc
        t2 = time.monotonic()
        timing = (
            f"Lista · transcribir {t1 - t0:.1f}s · "
            f"clipboard {t2 - t1:.1f}s · total {t2 - t0:.1f}s · "
            f"audio {audio_seconds:.1f}s · pcm {pcm_size_kib:.0f} KiB"
        )
        log.info("⏱️ %s", timing)
        notify_ready()

    def _install_signal_handlers(self, loop: asyncio.AbstractEventLoop) -> None:
        def handler() -> None:
            if self.shutdown.is_set():
                self.force_shutdown = True
            self.shutdown.set()

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, handler)
            except NotImplementedError:
                signal.signal(sig, lambda *_: handler())

    async def _cleanup(self) -> None:
        pcm = self.vad.drain()
        if pcm and not self.force_shutdown:
            try:
                await asyncio.wait_for(self._process_segment(pcm), timeout=30)
            except Exception as exc:
                log.warning("final speech drain skipped: %s", exc)
        await self.transcriber.stop_current(kill_after=0 if self.force_shutdown else 2)
        await self.capture.stop(kill=self.force_shutdown)
        self.injector.close()
        self.transcriber.cleanup_temp()


async def run_daemon(config: Config, duration: float | None = None) -> int:
    return await MainLoop(config, duration=duration).run()

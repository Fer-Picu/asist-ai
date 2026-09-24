from __future__ import annotations

import asyncio
import contextlib
import logging
import shutil
import tempfile
import wave
from pathlib import Path

log = logging.getLogger(__name__)


class ModelNotFoundError(RuntimeError):
    """Critical model error; daemon should exit with code 2."""


class WhisperTranscriber:
    def __init__(self, model_path: Path, threads: int = 4, language: str = "es", timeout: float | None = None) -> None:
        self.model_path = Path(model_path).expanduser()
        self.threads = threads
        self.language = "es" if language in {"", "auto"} else language
        self.timeout = timeout
        self.current_process: asyncio.subprocess.Process | None = None
        self.temp_dir = Path(tempfile.mkdtemp(prefix="asit-ia-"))

    def ensure_model(self) -> None:
        if not self.model_path.exists():
            raise ModelNotFoundError(f"Whisper model not found at {self.model_path}")

    async def transcribe_pcm(self, pcm_data: bytes, sample_rate: int = 16000, channels: int = 1) -> str:
        wav_path = self._write_wav(pcm_data, sample_rate, channels)
        try:
            return await self.transcribe_wav(wav_path)
        finally:
            with contextlib.suppress(FileNotFoundError):
                wav_path.unlink()

    async def transcribe_wav(self, wav_path: Path) -> str:
        self.ensure_model()
        if not self._valid_wav(wav_path):
            log.error("Invalid WAV format for transcription: %s", wav_path)
            return ""
        exe = shutil.which("whisper-cli") or shutil.which("whisper")
        if exe is None:
            log.error("whisper-cli not found in PATH")
            return ""
        cmd = [
            exe,
            "-m",
            str(self.model_path),
            "-f",
            str(wav_path),
            "--no-timestamps",
            "-l",
            self.language,
            "-t",
            str(self.threads),
        ]
        log.info("whisper-cli start: %s", " ".join(cmd))
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        self.current_process = proc
        try:
            if self.timeout is None:
                stdout, stderr = await proc.communicate()
            else:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.timeout)
        except asyncio.TimeoutError:
            log.warning("whisper-cli timed out after %.0fs for %s", self.timeout, wav_path)
            await self.stop_current(kill_after=2)
            return ""
        finally:
            self.current_process = None

        if stderr:
            for line in stderr.decode(errors="replace").splitlines():
                if line.strip():
                    log.info("whisper-cli: %s", line.strip())
        if proc.returncode not in (0, None):
            log.error("whisper-cli failed for %s: %s", wav_path, stderr.decode(errors="replace").strip())
            return ""
        log.info("whisper-cli done: exit=%s", proc.returncode)
        return _clean_output(stdout.decode(errors="replace"))

    async def stop_current(self, kill_after: float = 2.0) -> None:
        proc = self.current_process
        if not proc or proc.returncode is not None:
            return
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=kill_after)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()

    def cleanup_temp(self) -> None:
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_wav(self, pcm_data: bytes, sample_rate: int, channels: int) -> Path:
        handle = tempfile.NamedTemporaryFile(prefix="segment-", suffix=".wav", dir=self.temp_dir, delete=False)
        path = Path(handle.name)
        handle.close()
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(channels)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(pcm_data)
        return path

    @staticmethod
    def _valid_wav(path: Path) -> bool:
        try:
            with wave.open(str(path), "rb") as wav:
                return wav.getframerate() == 16000 and wav.getnchannels() == 1 and wav.getsampwidth() == 2
        except (wave.Error, FileNotFoundError):
            return False


def _clean_output(stdout: str) -> str:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    cleaned: list[str] = []
    for line in lines:
        if line.startswith("[") and "]" in line:
            line = line.split("]", 1)[1].strip()
        cleaned.append(line)
    return " ".join(cleaned).strip()

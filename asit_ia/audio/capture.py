from __future__ import annotations

import asyncio
import contextlib
import subprocess
from dataclasses import dataclass


class CaptureError(RuntimeError):
    """Critical capture failure; daemon should exit with code 1."""


@dataclass(slots=True)
class AudioDevice:
    source: str
    name: str
    description: str


class ArecordCapture:
    def __init__(self, sample_rate: int = 16000, channels: int = 1, audio_format: str = "S16_LE") -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.audio_format = audio_format
        self.process: asyncio.subprocess.Process | None = None

    async def start(self, device: str = "default") -> None:
        if self.process and self.process.returncode is None:
            return
        if _is_pipewire_source(device):
            self.process = await asyncio.create_subprocess_exec(
                "parecord",
                "-d", device,
                "--format=s16le",
                f"--rate={self.sample_rate}",
                f"--channels={self.channels}",
                "--raw",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        else:
            self.process = await asyncio.create_subprocess_exec(
                "arecord",
                "-D", device,
                "-f", self.audio_format,
                "-r", str(self.sample_rate),
                "-c", str(self.channels),
                "-t", "raw",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

    async def read(self, n_bytes: int) -> bytes:
        if not self.process or not self.process.stdout:
            raise CaptureError("arecord is not running")
        data = await self.process.stdout.readexactly(n_bytes)
        if not data:
            raise CaptureError("arecord produced no audio")
        return data

    async def stop(self, kill: bool = False) -> None:
        proc = self.process
        self.process = None
        if not proc or proc.returncode is not None:
            return
        if kill:
            proc.kill()
        else:
            proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=2)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()

    async def read_stderr(self) -> str:
        if not self.process or not self.process.stderr:
            return ""
        with contextlib.suppress(Exception):
            return (await asyncio.wait_for(self.process.stderr.read(), timeout=0.2)).decode(errors="replace")
        return ""


async def list_audio_devices() -> list[AudioDevice]:
    devices: list[AudioDevice] = []
    devices.extend(await _list_arecord_devices())
    devices.extend(await _list_pactl_sources())
    return devices


async def _list_arecord_devices() -> list[AudioDevice]:
    try:
        proc = await asyncio.create_subprocess_exec(
            "arecord", "-l", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
    except FileNotFoundError:
        return []
    results: list[AudioDevice] = []
    for line in stdout.decode(errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("card "):
            continue
        # card 1: Device [Name], device 0: USB Audio [USB Audio]
        parts = line.replace(":", "").split()
        try:
            card = parts[1]
            device_index = parts[parts.index("device") + 1]
            name = line.split(":", 1)[1].strip() if ":" in line else line
            results.append(AudioDevice("arecord", f"hw:{card},{device_index}", name))
        except (ValueError, IndexError):
            results.append(AudioDevice("arecord", "unknown", line))
    return results


async def _list_pactl_sources() -> list[AudioDevice]:
    try:
        proc = await asyncio.create_subprocess_exec(
            "pactl", "list", "sources", "short", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
    except FileNotFoundError:
        return []
    results: list[AudioDevice] = []
    for line in stdout.decode(errors="replace").splitlines():
        fields = line.split("\t")
        if len(fields) < 2:
            continue
        name = fields[1]
        if ".monitor" in name or "monitor" in name.lower():
            continue
        results.append(AudioDevice("pactl", name, line))
    return results


def format_devices(devices: list[AudioDevice]) -> str:
    if not devices:
        return "No capture devices found."
    return "\n".join(f"[{d.source}] {d.name} — {d.description}" for d in devices)


def detect_default_source() -> str | None:
    """Return the system default capture source from PipeWire/PulseAudio, or None."""
    import subprocess

    try:
        result = subprocess.run(
            ["pactl", "info"], capture_output=True, text=True, timeout=3
        )
    except (FileNotFoundError, subprocess.TimeoutError):
        return None
    for line in result.stdout.splitlines():
        if line.startswith("Default Source:"):
            return line.split(":", 1)[1].strip()
    return None


def _is_pipewire_source(device: str) -> bool:
    """Return True if *device* is a PulseAudio/PipeWire source name, not an ALSA device."""
    return bool("alsa_input" in device or "alsa_output" in device or device.startswith("bluez_"))

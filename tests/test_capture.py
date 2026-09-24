from __future__ import annotations

import asyncio

from asit_ia.audio.capture import ArecordCapture


def test_arecord_start_uses_configured_device_and_audio_contract(monkeypatch) -> None:
    calls: list[tuple[object, ...]] = []

    class FakeProcess:
        returncode = None

    async def fake_subprocess(*args: object, **_kwargs: object) -> FakeProcess:
        calls.append(args)
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)

    capture = ArecordCapture()
    asyncio.run(capture.start("hw:2,0"))

    assert calls == [
        (
            "arecord",
            "-D",
            "hw:2,0",
            "-f",
            "S16_LE",
            "-r",
            "16000",
            "-c",
            "1",
            "-t",
            "raw",
        )
    ]

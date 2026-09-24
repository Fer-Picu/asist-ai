from __future__ import annotations

import logging
from pathlib import Path
import shutil
import subprocess

log = logging.getLogger(__name__)

_READY_SOUND_CANDIDATES = (
    Path("/usr/share/sounds/freedesktop/stereo/complete.oga"),
    Path("/usr/share/sounds/ocean/stereo/completion-success.oga"),
    Path("/usr/share/sounds/oxygen/stereo/completion-success.ogg"),
)


def notify_ready() -> None:
    """Best-effort desktop notification after text is ready.

    Notification failures must never break transcription or clipboard output.
    """
    _show_ready_notification()
    _play_ready_sound()


def notify_failed() -> None:
    """Best-effort desktop notification when transcription produced no text."""
    _show_notification("asit-ia 🔴", urgency="normal")


def _show_ready_notification() -> None:
    _show_notification("asit-ia 🙂", urgency="normal")


def _show_notification(title: str, *, urgency: str) -> None:
    if not shutil.which("notify-send"):
        log.debug("notify-send not found; skipping desktop notification")
        return

    try:
        subprocess.run(
            [
                "notify-send",
                "--app-name=asit-ia",
                f"--urgency={urgency}",
                "--expire-time=2000",
                title,
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=1,
        )
    except Exception as exc:  # pragma: no cover - defensive best-effort guard
        log.warning("desktop notification skipped: %s", exc)


def _play_ready_sound() -> None:
    if not shutil.which("paplay"):
        log.debug("paplay not found; skipping ready sound")
        return

    sound_path = next((path for path in _READY_SOUND_CANDIDATES if path.exists()), None)
    if sound_path is None:
        log.debug("ready sound not found; skipping")
        return

    try:
        subprocess.Popen(
            ["paplay", "--volume=12000", str(sound_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:  # pragma: no cover - defensive best-effort guard
        log.debug("ready sound skipped: %s", exc)

from __future__ import annotations

import logging
import shutil
import subprocess

from asit_ia.injection.abc import Injector

log = logging.getLogger(__name__)

_BACKEND_CHAIN = ["qdbus6", "wl-copy", "xclip", "xsel"]


class ClipboardError(RuntimeError):
    """Clipboard backend unavailable or failed; daemon exits with code 3."""


class ClipboardInjector(Injector):
    """Multi-backend clipboard text injector.

    Detects the first available clipboard tool at init time
    (``qdbus6`` → ``wl-copy`` → ``xclip`` → ``xsel``) and writes
    text via subprocess.
    """

    def __init__(self) -> None:
        self._backend = self._detect_backend()

    # ------------------------------------------------------------------
    # Injector interface
    # ------------------------------------------------------------------

    def send_text(self, text: str) -> None:
        """Write *text* to the system clipboard via the detected backend."""
        cmd: list[str]
        if self._backend == "qdbus6":
            cmd = [
                "qdbus6",
                "org.kde.klipper",
                "/klipper",
                "org.kde.klipper.klipper.setClipboardContents",
                text,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
        else:
            cmd = _stdin_cmd(self._backend)
            result = subprocess.run(cmd, input=text, capture_output=True, text=True)

        if result.returncode != 0:
            raise ClipboardError(
                f"{self._backend} failed (exit {result.returncode}): "
                f"{result.stderr.strip()}"
            )

    def close(self) -> None:
        """No-op — no persistent resources to release."""

    def detect_display(self) -> bool:
        """Always return ``True`` — clipboard does not require X11/XWayland."""
        return True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _detect_backend(self) -> str:
        """Return the first installed backend in priority order."""
        for name in _BACKEND_CHAIN:
            if shutil.which(name):
                log.debug("clipboard backend: %s", name)
                return name
        raise ClipboardError(
            "No clipboard backend found. "
            "Install one of: qdbus6 (KDE), wl-copy (wl-clipboard), xclip, or xsel."
        )


def _stdin_cmd(backend: str) -> list[str]:
    """Build the subprocess command that reads text from stdin."""
    if backend == "wl-copy":
        return ["wl-copy"]
    if backend == "xclip":
        return ["xclip", "-selection", "clipboard"]
    if backend == "xsel":
        return ["xsel", "-ib"]
    raise ClipboardError(f"Unknown backend: {backend!r}")
